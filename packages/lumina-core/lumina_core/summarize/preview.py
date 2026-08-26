"""Short catalog lines for GET /segments — never the full summary_json."""

from __future__ import annotations

import json
from typing import Any

LIST_PREVIEW_MAX_CHARS = 160


def segment_list_fields(
    summary_json: Any,
    *,
    max_chars: int = LIST_PREVIEW_MAX_CHARS,
) -> tuple[str | None, list[str]]:
    """Return (summary_preview, bullet_labels). Never the JSON blob or bullet bodies."""
    parsed = _parse(summary_json)
    if parsed is None:
        return None, []
    return _preview_from_parsed(parsed, max_chars=max_chars), _labels_from_parsed(parsed)


def segment_list_preview(
    summary_json: Any,
    *,
    max_chars: int = LIST_PREVIEW_MAX_CHARS,
) -> str | None:
    """First sentence, else joined bullets. Not the 2–8 char inferred label."""
    preview, _ = segment_list_fields(summary_json, max_chars=max_chars)
    return preview


def segment_list_bullet_labels(summary_json: Any) -> list[str]:
    """Structured-point titles only (≤8 chars each). Empty when summary is missing."""
    _, labels = segment_list_fields(summary_json)
    return labels


def _preview_from_parsed(parsed: dict[str, Any], *, max_chars: int) -> str | None:
    for sentence in parsed.get("sentences") or []:
        text = str(sentence).strip()
        if text:
            return _clip(text, max_chars)

    parts: list[str] = []
    for item in parsed.get("bullets") or []:
        line = _bullet_line(item)
        if line:
            parts.append(line)
    if parts:
        return _clip(" · ".join(parts), max_chars)
    return None


def _labels_from_parsed(parsed: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for item in parsed.get("bullets") or []:
        label = _bullet_label(item)
        if label:
            labels.append(label)
    return labels


def _parse(summary_json: Any) -> dict[str, Any] | None:
    if summary_json is None:
        return None
    if isinstance(summary_json, dict):
        return summary_json
    if not isinstance(summary_json, str) or not summary_json.strip():
        return None
    try:
        parsed = json.loads(summary_json)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _bullet_line(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if not isinstance(item, dict):
        return ""
    label = str(item.get("label") or "").strip()
    body = str(item.get("body") or item.get("content") or item.get("text") or "").strip()
    if body and label:
        return f"{label}：{body}"
    return body or label


def _bullet_label(item: Any) -> str:
    if isinstance(item, str):
        return _label_from_bullet_string(item)
    if not isinstance(item, dict):
        return ""
    label = str(item.get("label") or item.get("tag") or "").strip()
    if label:
        return label[:8]
    body = str(item.get("body") or item.get("content") or item.get("text") or "").strip()
    return _label_from_bullet_string(body) if body else ""


def _label_from_bullet_string(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return ""
    for sep in ("：", ":"):
        if sep in cleaned:
            left, right = cleaned.split(sep, 1)
            left, right = left.strip(), right.strip()
            if left and right and len(left) <= 12 and "。" not in left:
                return left[:8]
    if len(cleaned) <= 8:
        return cleaned
    return cleaned[:8]


def _clip(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars == 1:
        return "…"
    return text[: max_chars - 1] + "…"
