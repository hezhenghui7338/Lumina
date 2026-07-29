"""Segment summarization."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from lumina_core.config import (
    MAX_SUMMARY_RETRIES,
    OLLAMA_CHUNK_MAX,
    OLLAMA_SUMMARY_MAX_RETRIES,
    OLLAMA_SUMMARY_MIN_BODY_CHARS,
)
from lumina_core.models.router import ProfileModelRouter
from lumina_core.summarize.schema import (
    SegmentSummary,
    parse_segment_summary,
    parse_segment_summary_minimal,
    validate_summary_richness,
)

SummaryProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]

SUMMARY_PROMPT = """你是阅读助手。为以下段落生成 JSON 摘要（速读卡）。

硬性规则：
- sentences: 1～最多 3 句概述；能一句说清就一句，禁止注水凑满三条
- bullets: 3～7 条结构化要点；每条为 {{"label":"…","body":"…"}}
  - label: ≤8 字的精炼小标题，仅作扫读索引
  - body: 1～2 句充实说明（40～120 字），交代人物/事件/因果/论据；禁止只写标签或短语
- notes: 0～3 条「需要注意」；仅在有局限、免责、反方观点、信息不完整时写，否则 []
- follow_ups: 2～3 个短问题；必须基于本段已覆盖内容、可继续深聊；禁止编造原文未涉及的细节；导语/过短段落可 []
- label: ≤20 字的段列表导航标签（浓缩本段主题）
- anchor: 锚点字符串，格式如「§章节 · 段 N」

只输出 JSON，不要其他文字。示例：
{{"sentences":["本段交代主角寒门出身与赴考之志。"],"bullets":[{{"label":"寒门出身","body":"主角生于贫苦农家，父亲早逝，母亲靠纺织维生；邻里虽敬其向学，却无力资助书卷。"}},{{"label":"赴考之志","body":"段末以誓要金榜题名收束，将个人命运与科举制度绑定，暗示后文赶考与权谋冲突。"}}],"notes":["本段为叙述性引子，尚未展开科举制度细节。"],"follow_ups":["主角与邻里期望之间有何张力？","赴考之志在后文如何遭遇挫折？"],"label":"引子：寒门赴考","anchor":"§第一章 · 段 1"}}

段落锚点：{anchor}
---
{text}
"""

SUMMARY_PROMPT_OLLAMA = """你是阅读助手。阅读以下段落，只输出 JSON，不要任何其他文字。

字段（仅这两个）：
- sentences: 1～3 句概述
- bullets: 3～7 条要点，每条 {{"label":"≤8字小标题","body":"1～2句说明"}}

示例：
{{"sentences":["本段交代主角寒门出身。"],"bullets":[{{"label":"寒门出身","body":"主角生于贫苦农家，父亲早逝。"}},{{"label":"赴考之志","body":"段末誓要金榜题名。"}},{{"label":"邻里关系","body":"邻里敬其向学但无力资助。"}}]}}

---
{text}
"""

_OLLAMA_RETRY_SUFFIX = (
    '\n\n上次输出不是合法 JSON。请只输出 '
    '{{"sentences":["…"],"bullets":[{{"label":"…","body":"…"}}]}}，不要其他文字。'
)


@dataclass
class SummarizeResult:
    summary: SegmentSummary
    llm_attempts: int
    llm_duration_s: float


def _segment_prompt_settings(router: ProfileModelRouter) -> tuple[str, int, int, int, bool]:
    """Return prompt template, text limit, retries, min bullet body chars, is_ollama."""
    models = getattr(router, "models", None)
    if models is not None and models.primary_summarize_is_ollama():
        return (
            SUMMARY_PROMPT_OLLAMA,
            OLLAMA_CHUNK_MAX,
            OLLAMA_SUMMARY_MAX_RETRIES,
            OLLAMA_SUMMARY_MIN_BODY_CHARS,
            True,
        )
    return SUMMARY_PROMPT, 8000, MAX_SUMMARY_RETRIES, 20, False


def _format_base_prompt(
    template: str,
    *,
    anchor_label: str,
    text: str,
    is_ollama: bool,
) -> str:
    if is_ollama:
        return template.format(text=text)
    return template.format(anchor=anchor_label, text=text)


def summarize_job_timeout_seconds(router: ProfileModelRouter) -> int:
    """Wall-clock budget for one summarize job (each LLM attempt may use full segment timeout)."""
    from lumina_core import config

    _, _, llm_retries, _, _ = _segment_prompt_settings(router)
    return config.SUMMARY_SEGMENT_TIMEOUT_SECONDS * max(1, llm_retries)


async def summarize_segment(
    router: ProfileModelRouter,
    *,
    raw_text: str,
    anchor_label: str,
    max_retries: int | None = None,
    failure_dump_path: Path | None = None,
    on_progress: SummaryProgressCallback | None = None,
) -> SummarizeResult:
    prompt_template, text_limit, default_retries, min_body_chars, is_ollama = (
        _segment_prompt_settings(router)
    )
    segment_text = raw_text[:text_limit]
    base_prompt = _format_base_prompt(
        prompt_template,
        anchor_label=anchor_label,
        text=segment_text,
        is_ollama=is_ollama,
    )
    prompt = base_prompt
    last_err: Exception | None = None
    last_raw: str | None = None
    retries = max_retries if max_retries is not None else default_retries
    total_llm_duration = 0.0

    async def _emit_progress(
        *,
        phase: str,
        llm_attempt: int,
        llm_duration_s: float | None = None,
    ) -> None:
        if on_progress is None:
            return
        payload: dict[str, Any] = {
            "type": "segment_summarize_progress",
            "phase": phase,
            "llm_attempt": llm_attempt,
            "max_llm_attempts": retries,
        }
        if llm_duration_s is not None:
            payload["llm_duration_s"] = llm_duration_s
        await on_progress(payload)

    for attempt in range(retries):
        import time

        from lumina_core.debug_agent_log import agent_log

        llm_attempt = attempt + 1
        await _emit_progress(phase="start", llm_attempt=llm_attempt)
        attempt_started = time.time()
        agent_log(
            hypothesis_id="B",
            location="segment.py:summarize_segment:attempt",
            message="LLM attempt start",
            data={
                "attempt": llm_attempt,
                "max_attempts": retries,
                "prompt_chars": len(prompt),
                "text_limit": text_limit,
            },
        )
        raw = await router.complete(
            prompt,
            profile="summarize",
            json_mode=True,
        )
        llm_duration = round(time.time() - attempt_started, 2)
        total_llm_duration += llm_duration
        if isinstance(raw, str):
            last_raw = raw
        try:
            if is_ollama:
                summary = parse_segment_summary_minimal(raw, fallback_anchor=anchor_label)
            else:
                summary = parse_segment_summary(raw)
                validate_summary_richness(summary, min_body_chars=min_body_chars)
            agent_log(
                hypothesis_id="B",
                location="segment.py:summarize_segment:success",
                message="LLM attempt succeeded",
                data={"attempt": llm_attempt, "llm_duration_s": llm_duration},
            )
            return SummarizeResult(
                summary=summary,
                llm_attempts=llm_attempt,
                llm_duration_s=round(total_llm_duration, 2),
            )
        except (ValidationError, json.JSONDecodeError, ValueError) as exc:
            last_err = exc
            agent_log(
                hypothesis_id="B",
                location="segment.py:summarize_segment:validation_fail",
                message="LLM output validation failed, will retry",
                data={
                    "attempt": llm_attempt,
                    "llm_duration_s": llm_duration,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:300],
                    "raw_len": len(last_raw or ""),
                },
            )
            await _emit_progress(
                phase="fail",
                llm_attempt=llm_attempt,
                llm_duration_s=llm_duration,
            )
        if attempt + 1 < retries and last_err is not None:
            if is_ollama:
                prompt = base_prompt + _OLLAMA_RETRY_SUFFIX
            elif isinstance(last_err, json.JSONDecodeError):
                prompt = (
                    base_prompt
                    + "\n\n上次输出不是合法 JSON，请只输出一个完整 JSON 对象，不要任何解释文字；"
                    "bullets 须为 {{label, body}} 对象数组。"
                )
            elif isinstance(last_err, ValueError):
                prompt = (
                    base_prompt
                    + f"\n\n上次输出不符合要求：{last_err}。"
                    "bullets 每条 body 须充实说明，禁止只写标签；"
                    "follow_ups 须基于本段已覆盖内容。"
                )
            elif isinstance(last_err, ValidationError):
                prompt = (
                    base_prompt
                    + "\n\n上次输出字段不符合要求（如 label 须 ≤20 字、bullets 须 3～7 条），"
                    "请严格按规则重新输出单个 JSON 对象。"
                )
    assert last_err is not None
    if failure_dump_path is not None and last_raw is not None:
        failure_dump_path.parent.mkdir(parents=True, exist_ok=True)
        failure_dump_path.write_text(last_raw, encoding="utf-8")
    raise last_err


def summary_to_json(summary: SegmentSummary) -> str:
    return json.dumps(summary.model_dump(), ensure_ascii=False)


def segment_ready_event_payload(
    summary: SegmentSummary,
    *,
    idx: int,
    resource_id: str,
    model: str,
    summary_duration_s: float | None = None,
    summary_llm_attempts: int | None = None,
) -> dict[str, Any]:
    """SSE segment_ready payload with nested and flat summary fields for UI."""
    dumped = summary.model_dump()
    payload: dict[str, Any] = {
        "type": "segment_ready",
        "idx": idx,
        "label": summary.label,
        "summary_status": "ready",
        "summary_json": summary_to_json(summary),
        "anchor_label": summary.anchor,
        "summary_provider": resource_id,
        "summary_model": model,
        "sentences": dumped["sentences"],
        "bullets": dumped["bullets"],
        "notes": dumped["notes"],
        "follow_ups": dumped["follow_ups"],
        "anchor": dumped["anchor"],
    }
    if summary_duration_s is not None:
        payload["summary_duration_s"] = round(summary_duration_s, 2)
    if summary_llm_attempts is not None:
        payload["summary_llm_attempts"] = summary_llm_attempts
    return payload
