"""Segment summarization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from lumina_core.config import (
    MAX_SUMMARY_RETRIES,
    OLLAMA_CHUNK_MAX,
    OLLAMA_SUMMARY_MAX_RETRIES,
    OLLAMA_SUMMARY_MIN_BODY_CHARS,
)
from lumina_core.models.router import ProfileModelRouter, parse_json_response
from lumina_core.summarize.schema import (
    SegmentSummary,
    normalize_summary_data,
    validate_summary_richness,
)

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

SUMMARY_PROMPT_OLLAMA = """你是阅读助手。为以下段落生成 JSON 速读卡，只输出 JSON。

字段：sentences(1-3句)、bullets(3-7条，{{label≤8字, body 40-120字}})、notes(0-3)、follow_ups(0-3)、label(≤20字)、anchor。

段落锚点：{anchor}
---
{text}
"""


def _segment_prompt_settings(router: ProfileModelRouter) -> tuple[str, int, int, int]:
    """Return prompt template, text limit, retries, and min bullet body chars."""
    models = getattr(router, "models", None)
    if models is not None and models.primary_summarize_is_ollama():
        return (
            SUMMARY_PROMPT_OLLAMA,
            OLLAMA_CHUNK_MAX,
            OLLAMA_SUMMARY_MAX_RETRIES,
            OLLAMA_SUMMARY_MIN_BODY_CHARS,
        )
    return SUMMARY_PROMPT, 8000, MAX_SUMMARY_RETRIES, 20


async def summarize_segment(
    router: ProfileModelRouter,
    *,
    raw_text: str,
    anchor_label: str,
    max_retries: int | None = None,
    failure_dump_path: Path | None = None,
) -> SegmentSummary:
    prompt_template, text_limit, default_retries, min_body_chars = _segment_prompt_settings(
        router
    )
    base_prompt = prompt_template.format(
        anchor=anchor_label,
        text=raw_text[:text_limit],
    )
    prompt = base_prompt
    last_err: Exception | None = None
    last_raw: str | None = None
    retries = max_retries if max_retries is not None else default_retries
    for attempt in range(retries):
        raw = await router.complete(prompt, profile="summarize", json_mode=True)
        if isinstance(raw, str):
            last_raw = raw
        try:
            summary = _parse_summary(raw, fallback_anchor=anchor_label)
            validate_summary_richness(summary, min_body_chars=min_body_chars)
            return summary
        except (ValidationError, json.JSONDecodeError, ValueError) as exc:
            last_err = exc
        if attempt + 1 < retries and last_err is not None:
            if isinstance(last_err, json.JSONDecodeError):
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


def _parse_summary(raw: str | dict, *, fallback_anchor: str) -> SegmentSummary:
    data = parse_json_response(raw) if isinstance(raw, str) else raw
    normalized = normalize_summary_data(data)
    if not isinstance(normalized.get("anchor"), str) or not normalized["anchor"].strip():
        normalized["anchor"] = fallback_anchor
    return SegmentSummary.model_validate(normalized)


def summary_to_json(summary: SegmentSummary) -> str:
    return json.dumps(summary.model_dump(), ensure_ascii=False)


def segment_ready_event_payload(
    summary: SegmentSummary,
    *,
    idx: int,
    resource_id: str,
    model: str,
) -> dict[str, Any]:
    """SSE segment_ready payload with nested and flat summary fields for UI."""
    dumped = summary.model_dump()
    return {
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
