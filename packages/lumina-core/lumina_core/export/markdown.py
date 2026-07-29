"""Markdown export — default includes translations."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from lumina_core.models.router import parse_json_response
from lumina_core.summarize.schema import BulletPoint, format_bullet, normalize_summary_data


def render_segment_summary_for_export(raw: str | dict) -> list[str]:
    """Lenient export rendering — mirrors macOS ParsedSummary (no full schema validate)."""
    data = parse_json_response(raw) if isinstance(raw, str) else raw
    normalized = normalize_summary_data(data)
    lines: list[str] = []

    sentences = normalized.get("sentences") or []
    if isinstance(sentences, list):
        for item in sentences:
            if isinstance(item, str) and item.strip():
                lines.append(item.strip())

    bullets = normalized.get("bullets") or []
    if isinstance(bullets, list):
        for item in bullets:
            if isinstance(item, dict):
                try:
                    bullet = BulletPoint.model_validate(item)
                    lines.append(f"- {format_bullet(bullet)}")
                except ValidationError:
                    label = str(item.get("label") or item.get("tag") or "").strip()
                    body = str(
                        item.get("body") or item.get("content") or item.get("text") or ""
                    ).strip()
                    if body:
                        prefix = f"{label}：" if label else ""
                        lines.append(f"- {prefix}{body}")
            elif isinstance(item, str) and item.strip():
                lines.append(f"- {item.strip()}")

    notes = normalized.get("notes") or []
    if isinstance(notes, list):
        note_lines = [
            str(n).strip() for n in notes if isinstance(n, str) and str(n).strip()
        ]
        if note_lines:
            lines.extend(["", "#### 需要注意"])
            lines.extend(f"- {n}" for n in note_lines)

    follow_ups = normalized.get("follow_ups") or []
    if isinstance(follow_ups, list):
        fu_lines = [
            str(q).strip() for q in follow_ups if isinstance(q, str) and str(q).strip()
        ]
        if fu_lines:
            lines.extend(["", "#### 你可以接着问"])
            for i, q in enumerate(fu_lines, 1):
                lines.append(f"{i}. {q}")

    return lines


def export_book_markdown(
    book: dict[str, Any],
    segments: list[dict[str, Any]],
    *,
    include_notes: bool = False,
    notes: list[dict[str, Any]] | None = None,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        f"# 《{book.get('title', 'Untitled')}》摘要版",
        f"> 由 Lumina 生成 · {now}",
        "",
        "## 元信息",
        f"- 作者: {book.get('author') or '—'}",
        f"- 格式: {book.get('format', '—')}",
        f"- 段数: {book.get('segment_count', len(segments))}",
        "",
        "## 段摘要",
    ]

    for seg in segments:
        idx = seg["idx"] + 1
        anchor = seg.get("anchor_label") or f"段 {idx}"
        lines.append(f"### 段 {idx} · {anchor.strip('〔〕')}")
        summary = seg.get("summary_json")
        if summary:
            try:
                rendered = render_segment_summary_for_export(summary)
                if rendered:
                    lines.extend(rendered)
                else:
                    lines.append("_摘要未生成_")
            except (json.JSONDecodeError, TypeError, ValueError, ValidationError):
                lines.append(str(summary))
        else:
            lines.append("_摘要未生成_")
        lines.append("")

        translation = seg.get("translation")
        if translation:
            lines.extend([f"#### 译文 · 段 {idx}", translation, ""])

    if include_notes and notes:
        lines.extend(["## 我的笔记", ""])
        for note in notes:
            lines.append(f"- {note.get('content', '')}")

    return "\n".join(lines).strip() + "\n"
