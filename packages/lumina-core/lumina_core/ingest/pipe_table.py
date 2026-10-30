"""Normalize tabular rows into pipe/GFM plain text for raw_text."""

from __future__ import annotations

import re


def _cell(value: str) -> str:
    text = re.sub(r"\s+", " ", (value or "")).replace("|", "\\|").strip()
    return text


def format_pipe_table(rows: list[list[str]], *, header: bool = True) -> str:
    """Return a blank-line-wrapped GFM-ish pipe table, or empty string."""
    normalized: list[list[str]] = []
    for row in rows:
        cells = [_cell(c) for c in row]
        if any(cells):
            normalized.append(cells)
    if not normalized:
        return ""

    width = max(len(r) for r in normalized)
    padded = [r + [""] * (width - len(r)) for r in normalized]

    def line(cells: list[str]) -> str:
        return "| " + " | ".join(cells) + " |"

    lines = [line(padded[0])]
    if header:
        lines.append("| " + " | ".join("---" for _ in range(width)) + " |")
    lines.extend(line(r) for r in padded[1:])
    body = "\n".join(lines)
    return f"\n\n{body}\n\n"
