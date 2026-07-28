"""Segment summarization."""

from __future__ import annotations

import json

from lumina_core.models.router import ProfileModelRouter
from lumina_core.summarize.schema import SegmentSummary, parse_segment_summary

SUMMARY_PROMPT = """你是阅读助手。为以下段落生成 JSON 摘要。

要求：
- sentences: 最多三句话概述
- bullets: 3-7 条要点
- label: ≤20 字的段列表导航标签
- anchor: 锚点字符串，格式如「§章节 · 段 N」

只输出 JSON，不要其他文字。

段落锚点：{anchor}
---
{text}
"""


async def summarize_segment(
    router: ProfileModelRouter,
    *,
    raw_text: str,
    anchor_label: str,
) -> SegmentSummary:
    prompt = SUMMARY_PROMPT.format(anchor=anchor_label, text=raw_text[:8000])
    raw = await router.complete(prompt, profile="summarize", json_mode=True)
    return parse_segment_summary(raw)


def summary_to_json(summary: SegmentSummary) -> str:
    return json.dumps(summary.model_dump(), ensure_ascii=False)
