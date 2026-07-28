"""Markdown export — default includes translations."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


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
                data = json.loads(summary) if isinstance(summary, str) else summary
                for s in data.get("sentences", []):
                    lines.append(s)
                for b in data.get("bullets", []):
                    lines.append(f"- {b}")
            except (json.JSONDecodeError, TypeError):
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
