"""Segment summarization."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from lumina_core.config import (
    MAX_SUMMARY_RETRIES,
    OLLAMA_SUMMARY_MAX_RETRIES,
    OLLAMA_SUMMARY_MIN_BODY_CHARS,
    PromptsConfig,
    load_prompts_config,
    resolve_chunk_budget,
)
from lumina_core.models.router import ProfileModelRouter
from lumina_core.prompts_defaults import DEFAULT_SEGMENT_QUALITY
from lumina_core.summarize.quality import SummaryQualityError, inspect_summary_quality
from lumina_core.summarize.schema import (
    SegmentSummary,
    parse_segment_summary,
    parse_segment_summary_minimal,
    validate_summary_richness,
)

SummaryProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]

ProviderKind = Literal["ollama", "cloud", "full"]
SUMMARY_CONTEXT_MAX_CHARS = 1600
SUMMARY_CONTEXT_QUERY_LIMIT = 32

_CONTEXT_GUIDANCE = """以下是当前段之前的摘要背景，仅用于消解人物、代词、时间线和因果关系：
{context}

背景使用规则：
- 只总结当前待摘要段落，不能把背景中的事件当作当前段内容
- 不得仅因段首出现某个人名，就把后文的“我”或其他代词认定为此人
- 第一人称「我」是书中叙述者，禁止写成「阅读助手」或任何系统身份
- 只有原文或背景明确支持时才能确定人物身份；无法确认时保留不确定性

以下是当前待摘要段落：
"""

_OLLAMA_RETRY_SUFFIX = (
    '\n\n上次输出不是合法 JSON。请只输出 '
    '{{"sentences":["…"],"bullets":[{{"label":"…","body":"…"}}],"follow_ups":["…"]}}，不要其他文字。'
)

_CLOUD_RETRY_SUFFIX = (
    '\n\n上次输出不是合法 JSON。请只输出 '
    '{{"sentences":["…"],"bullets":[{{"label":"…","body":"…"}}],"follow_ups":["…"]}}，不要其他文字。'
)


@dataclass
class SummarizeResult:
    summary: SegmentSummary
    llm_attempts: int
    llm_duration_s: float


def _segment_prompt_settings(
    router: ProfileModelRouter,
    prompts: PromptsConfig,
) -> tuple[str, int, int, int, bool, bool, ProviderKind]:
    """Return prompt template, text limit, retries, min body chars, text-only, minimal parse, provider kind."""
    models = getattr(router, "models", None)
    text_limit = resolve_chunk_budget(models).max_chars
    if models is not None and models.primary_summarize_is_ollama():
        template = prompts.segment_ollama or prompts.segment
        return (
            template,
            text_limit,
            OLLAMA_SUMMARY_MAX_RETRIES,
            OLLAMA_SUMMARY_MIN_BODY_CHARS,
            "{anchor}" not in template,
            True,
            "ollama",
        )
    if models is not None and models.primary_summarize_is_cloud():
        template = prompts.segment_cloud or prompts.segment
        return (
            template,
            text_limit,
            MAX_SUMMARY_RETRIES,
            OLLAMA_SUMMARY_MIN_BODY_CHARS,
            "{anchor}" not in template,
            True,
            "cloud",
        )
    return (
        prompts.segment,
        text_limit,
        MAX_SUMMARY_RETRIES,
        20,
        False,
        False,
        "full",
    )


def _format_base_prompt(
    template: str,
    *,
    anchor_label: str,
    text: str,
    text_only: bool,
    background_context: str | None = None,
) -> str:
    if text_only:
        prompt = template.format(text=text)
    else:
        prompt = template.format(anchor=anchor_label, text=text)
    if not background_context:
        return prompt
    return _CONTEXT_GUIDANCE.format(context=background_context) + prompt


def _summary_row_text(row: dict[str, Any], *, scope: str) -> str | None:
    try:
        raw = row.get("summary_json")
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    parts = [str(item).strip() for item in parsed.get("sentences", []) if str(item).strip()]
    for bullet in parsed.get("bullets", []):
        if not isinstance(bullet, dict):
            continue
        label = str(bullet.get("label") or "").strip()
        body = str(bullet.get("body") or "").strip()
        if body:
            parts.append(f"{label}：{body}" if label else body)
    if not parts:
        return None
    return f"[{scope}·段 {int(row['idx']) + 1}] " + " ".join(parts)


def build_summary_context(
    rows: list[dict[str, Any]],
    *,
    current_chapter: str | None,
    max_chars: int = SUMMARY_CONTEXT_MAX_CHARS,
) -> str | None:
    """Build a bounded previous-chapter/current-chapter context from newest-first rows."""
    if max_chars <= 0:
        return None
    normalized_current = (current_chapter or "").strip() or None
    selected: list[tuple[dict[str, Any], str]] = []

    if normalized_current is None:
        selected = [(row, "前文") for row in rows[:6]]
    else:
        previous_chapter: str | None = None
        previous_chapter_found = False
        for row in rows:
            chapter = (row.get("chapter") or "").strip() or None
            if chapter == normalized_current:
                selected.append((row, "本章前文"))
                continue
            if not previous_chapter_found:
                previous_chapter = chapter
                previous_chapter_found = True
            if chapter == previous_chapter:
                selected.append((row, "上一章"))
            else:
                break

    # Favor the nearest summaries, then render retained items in reading order.
    retained: list[tuple[int, str]] = []
    used = 0
    for row, scope in selected:
        text = _summary_row_text(row, scope=scope)
        if not text:
            continue
        remaining = max_chars - used
        if remaining <= 0:
            break
        if len(text) > remaining:
            if retained:
                break
            text = text[:remaining].rstrip()
        retained.append((int(row["idx"]), text))
        used += len(text) + 1
    if not retained:
        return None
    retained.sort(key=lambda item: item[0])
    return "\n".join(text for _, text in retained)


def summarize_job_timeout_seconds(
    router: ProfileModelRouter,
    prompts: PromptsConfig | None = None,
) -> int:
    """Wall-clock budget for generation plus an optional quality review per attempt."""
    from lumina_core import config

    resolved = prompts or load_prompts_config()
    _, _, llm_retries, _, _, _, _ = _segment_prompt_settings(router, resolved)
    return config.SUMMARY_SEGMENT_TIMEOUT_SECONDS * max(1, llm_retries) * 2


async def summarize_segment(
    router: ProfileModelRouter,
    *,
    raw_text: str,
    anchor_label: str,
    summary_tier: Literal["normal", "advanced"] = "normal",
    max_retries: int | None = None,
    failure_dump_path: Path | None = None,
    on_progress: SummaryProgressCallback | None = None,
    prompts: PromptsConfig | None = None,
    background_context: str | None = None,
) -> SummarizeResult:
    resolved = prompts or load_prompts_config()
    prompt_template, text_limit, default_retries, min_body_chars, text_only, use_minimal_parse, provider_kind = (
        _segment_prompt_settings(router, resolved)
    )
    segment_text = raw_text[:text_limit]
    base_prompt = _format_base_prompt(
        prompt_template,
        anchor_label=anchor_label,
        text=segment_text,
        text_only=text_only,
        background_context=background_context,
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

        async def _on_slot_acquired(current_attempt: int = llm_attempt) -> None:
            await _emit_progress(phase="llm_start", llm_attempt=current_attempt)

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
        complete_kwargs: dict[str, Any] = {
            "profile": "summarize",
            "json_mode": True,
            "on_slot_acquired": _on_slot_acquired,
        }
        if summary_tier == "advanced":
            complete_kwargs["summary_tier"] = summary_tier
        raw = await router.complete(prompt, **complete_kwargs)
        llm_duration = round(time.time() - attempt_started, 2)
        total_llm_duration += llm_duration
        if isinstance(raw, str):
            last_raw = raw
        try:
            if use_minimal_parse:
                summary = parse_segment_summary_minimal(raw, fallback_anchor=anchor_label)
            else:
                summary = parse_segment_summary(raw)
                validate_summary_richness(summary, min_body_chars=min_body_chars)
            quality = await inspect_summary_quality(
                router,
                raw_text=segment_text,
                summary=summary,
                review_prompt=resolved.segment_quality or DEFAULT_SEGMENT_QUALITY,
                summary_tier=summary_tier,
            )
            if quality.review_duration_s:
                llm_duration = round(llm_duration + quality.review_duration_s, 2)
                total_llm_duration += quality.review_duration_s
            if len(quality.issues) > 1:
                raise SummaryQualityError(quality.issues)
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
            if isinstance(last_err, SummaryQualityError):
                prompt = (
                    base_prompt
                    + f"\n\n上次摘要未通过质量检查：{last_err}。"
                    "请逐项重写有问题的句子或要点，确保文字完整、清晰、无乱码；"
                    "仍须严格输出规定的单个 JSON 对象，不要解释。"
                )
            elif use_minimal_parse:
                suffix = _OLLAMA_RETRY_SUFFIX if provider_kind == "ollama" else _CLOUD_RETRY_SUFFIX
                prompt = base_prompt + suffix
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
    summary_tier: Literal["normal", "advanced"] = "normal",
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
        "summary_tier": summary_tier,
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
