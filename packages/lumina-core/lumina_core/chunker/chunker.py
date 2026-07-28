"""Text chunker — chapter-aware splitting for Phase 0 tests."""

from __future__ import annotations

import re
from dataclasses import dataclass

from lumina_core.config import CHUNK_MAX_CHARS, CHUNK_TARGET_CHARS, SHORT_BOOK_MAX_CHARS

CHAPTER_PATTERN = re.compile(
    r"^(?:第[零一二三四五六七八九十百千\d]+[章节篇回]|§\s*.+)$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class ChunkSegment:
    index: int
    raw_text: str
    start_offset: int
    end_offset: int
    chapter: str | None = None


def chunk_text(text: str, *, target_chars: int = CHUNK_TARGET_CHARS) -> list[ChunkSegment]:
    """Split text into segments; short books stay as one segment."""
    text = text.strip()
    if not text:
        return []

    if len(text) <= SHORT_BOOK_MAX_CHARS:
        return [ChunkSegment(index=0, raw_text=text, start_offset=0, end_offset=len(text))]

    chapter_starts = [m.start() for m in CHAPTER_PATTERN.finditer(text)]
    if not chapter_starts or chapter_starts[0] != 0:
        chapter_starts = [0, *chapter_starts]

    segments: list[ChunkSegment] = []
    cursor = 0
    idx = 0

    while cursor < len(text):
        remaining = len(text) - cursor
        if remaining <= CHUNK_MAX_CHARS:
            chunk = text[cursor:]
            chapter = _chapter_at(text, cursor, chapter_starts)
            segments.append(
                ChunkSegment(
                    index=idx,
                    raw_text=chunk,
                    start_offset=cursor,
                    end_offset=cursor + len(chunk),
                    chapter=chapter,
                )
            )
            break

        end = min(cursor + target_chars, len(text))
        split_at = _find_split_point(text, cursor, end, chapter_starts)
        chunk = text[cursor:split_at]
        segments.append(
            ChunkSegment(
                index=idx,
                raw_text=chunk,
                start_offset=cursor,
                end_offset=split_at,
                chapter=_chapter_at(text, cursor, chapter_starts),
            )
        )
        cursor = split_at
        idx += 1

    return segments


def _chapter_at(text: str, offset: int, chapter_starts: list[int]) -> str | None:
    active = [s for s in chapter_starts if s <= offset]
    if not active:
        return None
    start = active[-1]
    line_end = text.find("\n", start)
    header = text[start : line_end if line_end != -1 else start + 80].strip()
    return header or None


def _find_split_point(text: str, start: int, end: int, chapter_starts: list[int]) -> int:
    """Prefer paragraph / chapter boundaries within the target window."""
    window = text[start:end]

    # Next chapter inside window → split before it (don't cross chapters)
    for cs in chapter_starts:
        if start < cs < end:
            return cs

    # Paragraph break (double newline)
    para = window.rfind("\n\n")
    if para > len(window) // 3:
        return start + para + 2

    # Single newline
    nl = window.rfind("\n")
    if nl > len(window) // 3:
        return start + nl + 1

    return end
