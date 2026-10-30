"""LLM prompt template persistence and merge."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lumina_core.config import PromptsConfig, load_prompts_config, normalize_segment_styles

_PROMPT_FIELDS = (
    "segment",
    "segment_ollama",
    "segment_cloud",
    "segment_quality",
    "document",
    "chat",
    "news_chat",
    "translate",
    "classify",
    "rollup",
    "document_map",
    "book_intro",
    "segment_styles",
)


def default_prompts() -> PromptsConfig:
    return load_prompts_config()


def _overlay_prompts(base: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for field in _PROMPT_FIELDS:
        if field not in raw:
            continue
        value = raw[field]
        if field == "segment_styles":
            merged[field] = normalize_segment_styles(
                {**(merged.get("segment_styles") or {}), **(value if isinstance(value, dict) else {})}
            )
            continue
        if field in ("segment_ollama", "segment_cloud", "segment_quality"):
            if value is None or (isinstance(value, str) and not value.strip()):
                merged[field] = None
            else:
                merged[field] = value
        elif field in ("rollup", "document_map", "book_intro"):
            if isinstance(value, str) and value.strip():
                merged[field] = value
        elif isinstance(value, str) and value.strip():
            merged[field] = value
    return merged


def load_prompts(data_dir: Path) -> PromptsConfig:
    """Load bundled defaults, overlay config.json prompts field."""
    base = default_prompts().model_dump()
    path = data_dir / "config.json"
    if path.exists():
        import json

        raw = json.loads(path.read_text(encoding="utf-8")) or {}
        prompts_raw = raw.get("prompts")
        if isinstance(prompts_raw, dict):
            base = _overlay_prompts(base, prompts_raw)
    return PromptsConfig.model_validate(base)


def merge_prompts(incoming: PromptsConfig, existing: PromptsConfig) -> PromptsConfig:
    """Merge PUT body with existing prompts; null/empty optional overrides clear."""
    data = existing.model_dump()
    incoming_data = incoming.model_dump()
    for field in _PROMPT_FIELDS:
        if field not in incoming_data:
            continue
        value = incoming_data[field]
        if field == "segment_styles":
            if isinstance(value, dict):
                data[field] = normalize_segment_styles(
                    {**(data.get("segment_styles") or {}), **value}
                )
            continue
        if field in ("segment_ollama", "segment_cloud", "segment_quality"):
            if value is None or (isinstance(value, str) and not value.strip()):
                data[field] = None
            else:
                data[field] = value
        elif field in ("rollup", "document_map", "book_intro"):
            if isinstance(value, str) and value.strip():
                data[field] = value
        elif isinstance(value, str) and value.strip():
            data[field] = value
    merged = PromptsConfig.model_validate(data)
    merged.validate_placeholders()
    return merged


def prompts_to_dict(prompts: PromptsConfig) -> dict[str, Any]:
    data = prompts.model_dump()
    data["segment_styles"] = normalize_segment_styles(data.get("segment_styles"))
    return data
