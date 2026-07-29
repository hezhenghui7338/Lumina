"""Segment summary JSON schema (TDD §4.3)."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

from lumina_core.models.router import parse_json_response


class BulletPoint(BaseModel):
    label: str = Field(max_length=8)
    body: str = Field(min_length=1, max_length=300)


class SegmentSummary(BaseModel):
    sentences: list[str] = Field(min_length=1, max_length=3)
    bullets: list[BulletPoint] = Field(min_length=3, max_length=7)
    notes: list[str] = Field(default_factory=list, max_length=3)
    follow_ups: list[str] = Field(default_factory=list, max_length=3)
    label: str = Field(max_length=20)
    anchor: str

    @field_validator("label")
    @classmethod
    def label_max_chars(cls, v: str) -> str:
        if len(v) > 20:
            raise ValueError(f"label exceeds 20 chars: {len(v)}")
        return v


def validate_summary_richness(
    summary: SegmentSummary,
    *,
    min_body_chars: int = 20,
) -> None:
    """Raise ValueError when LLM output is too terse (triggers retry)."""
    for i, bullet in enumerate(summary.bullets):
        if len(bullet.body.strip()) < min_body_chars:
            raise ValueError(
                f"bullets[{i}].body too short ({len(bullet.body)} chars, need ≥{min_body_chars})"
            )


def normalize_summary_data(data: dict) -> dict:
    """Normalize legacy and new summary JSON into schema-compatible dict."""
    out = dict(data)
    anchor = out.get("anchor") or out.get("锚点")
    if isinstance(anchor, str) and anchor.strip():
        out["anchor"] = anchor.strip()
    bullets = out.get("bullets")
    if isinstance(bullets, list):
        out["bullets"] = _normalize_bullets(bullets)
    if "notes" not in out or not isinstance(out.get("notes"), list):
        out["notes"] = []
    else:
        out["notes"] = [
            str(n).strip() for n in out["notes"] if isinstance(n, str) and n.strip()
        ][:3]
    if "follow_ups" not in out or not isinstance(out.get("follow_ups"), list):
        out["follow_ups"] = []
    else:
        out["follow_ups"] = [
            str(q).strip() for q in out["follow_ups"] if isinstance(q, str) and q.strip()
        ][:3]
    label = out.get("label")
    if isinstance(label, str) and len(label) > 20:
        out["label"] = label[:20]
    return out


def _normalize_bullets(items: list[object]) -> list[dict[str, str]]:
    flat: list[dict[str, str]] = []
    for item in items:
        if isinstance(item, list):
            flat.extend(_normalize_bullets(item))
        else:
            flat.append(_coerce_bullet_object(item))
    return flat


def _coerce_bullet_object(item: object) -> dict[str, str]:
    if isinstance(item, dict):
        label = str(item.get("label") or item.get("tag") or "").strip()
        body = str(item.get("body") or item.get("content") or item.get("text") or "").strip()
        if label and body:
            return {"label": label[:8], "body": body[:300]}
        if body:
            return {"label": label[:8] if label else _infer_label(body), "body": body[:300]}
        if label:
            return {"label": label[:8], "body": label}
        return {"label": "要点", "body": str(item)[:300]}
    text = str(item).strip()
    return _split_bullet_string(text)


def _split_bullet_string(text: str) -> dict[str, str]:
    cleaned = text
    while cleaned.startswith("- ") or cleaned.startswith("• ") or cleaned.startswith("* "):
        cleaned = cleaned[2:].strip()

    if cleaned.startswith("**"):
        match = re.match(r"\*\*(.+?)\*\*[：:]\s*(.+)", cleaned, re.DOTALL)
        if match:
            label, body = match.group(1).strip(), match.group(2).strip()
            if label and body:
                return {"label": label[:8], "body": body[:300]}

    for sep in ("：", ":"):
        if sep in cleaned:
            label, body = cleaned.split(sep, 1)
            label, body = label.strip(), body.strip()
            if label and body and len(label) <= 12 and "。" not in label:
                return {"label": label[:8], "body": body[:300]}

    if len(cleaned) <= 8:
        return {"label": cleaned, "body": cleaned}
    return {"label": _infer_label(cleaned), "body": cleaned[:300]}


def _infer_label(text: str) -> str:
    for sep in ("，", "。", "；", " "):
        if sep in text:
            candidate = text.split(sep, 1)[0].strip()
            if 2 <= len(candidate) <= 8:
                return candidate
    return text[:8] if text else "要点"


def parse_segment_summary(raw: str | dict) -> SegmentSummary:
    data = parse_json_response(raw) if isinstance(raw, str) else raw
    normalized = normalize_summary_data(data)
    return SegmentSummary.model_validate(normalized)


def format_bullet(b: BulletPoint) -> str:
    if b.label:
        return f"{b.label}：{b.body}"
    return b.body


def format_summary_text(summary: SegmentSummary) -> str:
    lines: list[str] = []
    if summary.sentences:
        lines.append("总结: " + " ".join(summary.sentences))
    if summary.bullets:
        lines.append("结构化要点:")
        lines.extend(f"- {format_bullet(b)}" for b in summary.bullets)
    if summary.notes:
        lines.append("需要注意:")
        lines.extend(f"- {n}" for n in summary.notes)
    if summary.follow_ups:
        lines.append("你可以接着问:")
        lines.extend(f"- {q}" for q in summary.follow_ups)
    return "\n".join(lines)
