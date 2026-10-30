"""Resolve per-book segment summary style guidance."""

from __future__ import annotations

from lumina_core.classify.book import normalize_category
from lumina_core.config import PromptsConfig
from lumina_core.prompts_defaults import DEFAULT_SEGMENT_STYLES

SEGMENT_STYLE_KEYS: tuple[str, ...] = (
    "文学",
    "历史",
    "科技",
    "哲学",
    "经济",
    "传记",
    "其他",
    "古文",
)


def resolve_segment_style_key(
    *,
    category: str | None = None,
    text_style: str | None = None,
) -> str:
    """Classical text_style wins; else book category; missing → 其他."""
    if (text_style or "").strip().lower() == "classical":
        return "古文"
    return normalize_category(category)


def resolve_segment_style_guidance(
    prompts: PromptsConfig,
    *,
    category: str | None = None,
    text_style: str | None = None,
) -> str:
    styles = prompts.segment_styles or DEFAULT_SEGMENT_STYLES
    key = resolve_segment_style_key(category=category, text_style=text_style)
    text = (styles.get(key) or styles.get("其他") or DEFAULT_SEGMENT_STYLES["其他"]).strip()
    return text or DEFAULT_SEGMENT_STYLES["其他"]
