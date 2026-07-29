"""Text chunker — structure-aware splitting with semantic boundaries."""

from __future__ import annotations

import re
from dataclasses import dataclass

from lumina_core.config import (
    CHUNK_MAX_CHARS,
    CHUNK_MIN_CHARS,
    CHUNK_TARGET_CHARS,
    ChunkBudget,
    SHORT_BOOK_MAX_CHARS,
)

# Traditional chapter headers (line-start)
CHAPTER_PATTERN = re.compile(
    r"^(?:第[零一二三四五六七八九十百千\d]+[章节篇回].*|§\s*.+)$",
    re.MULTILINE,
)

# Ingest-injected structure markers (EPUB § / PDF page)
STRUCTURE_PATTERN = re.compile(
    r"^## \[(?:§(.+)|p\.(\d+)(?:\s+无文本)?)\]$",
    re.MULTILINE,
)

# Sentence-ending punctuation (CN + EN) with optional closing quotes/brackets
SENTENCE_END_PATTERN = re.compile(r'[。！？；.!?][」』"\'\)\]】]*')


@dataclass(frozen=True)
class ChunkSegment:
    index: int
    raw_text: str
    start_offset: int
    end_offset: int
    chapter: str | None = None
    page_range: str | None = None


def chunk_text(
    text: str,
    *,
    target_chars: int = CHUNK_TARGET_CHARS,
    max_chars: int = CHUNK_MAX_CHARS,
    min_chars: int = CHUNK_MIN_CHARS,
    budget: ChunkBudget | None = None,
) -> list[ChunkSegment]:
    """Split text into segments; short books stay as one segment."""
    if budget is not None:
        target_chars = budget.target_chars
        max_chars = budget.max_chars
        min_chars = budget.min_chars

    text = text.strip()
    if not text:
        return []

    if len(text) <= SHORT_BOOK_MAX_CHARS:
        return [
            ChunkSegment(
                index=0,
                raw_text=text,
                start_offset=0,
                end_offset=len(text),
                chapter=_chapter_at(text, 0),
                page_range=_page_range_in(text, 0, len(text)),
            )
        ]

    structure_starts = _structure_starts(text)
    raw_segments: list[ChunkSegment] = []
    cursor = 0
    idx = 0

    while cursor < len(text):
        remaining = len(text) - cursor
        if remaining <= max_chars:
            chunk = text[cursor:]
            raw_segments.append(
                _make_segment(idx, text, cursor, cursor + len(chunk))
            )
            break

        window_end = min(cursor + max_chars, len(text))
        target_end = min(cursor + target_chars, len(text))
        split_at = _find_split_point(
            text,
            cursor,
            target_end,
            window_end,
            structure_starts,
            min_chars=min_chars,
        )
        if split_at <= cursor:
            split_at = window_end
        raw_segments.append(_make_segment(idx, text, cursor, split_at))
        cursor = split_at
        idx += 1

    segments = _rebalance(
        raw_segments,
        text,
        structure_starts,
        target_chars=target_chars,
        max_chars=max_chars,
        min_chars=min_chars,
    )
    _assert_coverage(text, segments)
    return segments


def _structure_starts(text: str) -> list[int]:
    """All structure boundary offsets: ingest markers + traditional chapter headers."""
    starts = {m.start() for m in STRUCTURE_PATTERN.finditer(text)}
    starts.update(m.start() for m in CHAPTER_PATTERN.finditer(text))
    ordered = sorted(starts)
    if not ordered or ordered[0] != 0:
        return [0, *ordered]
    return ordered


def _make_segment(idx: int, text: str, start: int, end: int) -> ChunkSegment:
    return ChunkSegment(
        index=idx,
        raw_text=text[start:end],
        start_offset=start,
        end_offset=end,
        chapter=_chapter_at(text, start),
        page_range=_page_range_in(text, start, end),
    )


def _chapter_at(text: str, offset: int) -> str | None:
    """Extract chapter title from nearest structure marker at or before offset."""
    best: str | None = None
    for m in STRUCTURE_PATTERN.finditer(text):
        if m.start() > offset:
            break
        if m.group(1):
            best = f"§{m.group(1).strip()}"
    if best:
        return best

    chapter_starts = [m.start() for m in CHAPTER_PATTERN.finditer(text)]
    active = [s for s in chapter_starts if s <= offset]
    if not active:
        return None
    start = active[-1]
    line_end = text.find("\n", start)
    header = text[start : line_end if line_end != -1 else start + 80].strip()
    return header or None


def _page_range_in(text: str, start: int, end: int) -> str | None:
    """Build p.N or p.N-M from PDF page markers within [start, end)."""
    pages: list[int] = []
    for m in STRUCTURE_PATTERN.finditer(text):
        pos = m.start()
        if pos >= end:
            break
        if pos >= start and m.group(2):
            pages.append(int(m.group(2)))
    if not pages:
        return None
    if len(pages) == 1:
        return f"p.{pages[0]}"
    return f"p.{pages[0]}-{pages[-1]}"


def _find_split_point(
    text: str,
    start: int,
    target_end: int,
    window_end: int,
    structure_starts: list[int],
    *,
    min_chars: int,
) -> int:
    """Find best split within [start, window_end], preferring boundaries near target_end."""
    # Never cross a structure marker inside the window (except at start)
    for ss in structure_starts:
        if start < ss < window_end:
            return ss

    search_from = max(start + min_chars // 2, start + 1)
    search_to = window_end

    # Search backward from target_end for natural boundaries
    for boundary_end in range(min(target_end, search_to), search_from - 1, -1):
        snippet = text[start:boundary_end]
        if not snippet:
            continue

        # Paragraph break
        para = snippet.rfind("\n\n")
        if para >= 0 and start + para + 2 >= search_from:
            return start + para + 2

        # Single newline
        nl = snippet.rfind("\n")
        if nl >= 0 and start + nl + 1 >= search_from:
            return start + nl + 1

        # Sentence boundary
        sent = _last_sentence_end(snippet)
        if sent is not None and start + sent >= search_from:
            return start + sent

    return window_end


def _last_sentence_end(snippet: str) -> int | None:
    """Return end offset (exclusive) after last sentence-ending punctuation in snippet."""
    last: int | None = None
    for m in SENTENCE_END_PATTERN.finditer(snippet):
        last = m.end()
    return last


def _rebalance(
    segments: list[ChunkSegment],
    text: str,
    structure_starts: list[int],
    *,
    target_chars: int,
    max_chars: int,
    min_chars: int,
) -> list[ChunkSegment]:
    """Merge undersized segments and split oversized ones at sentence boundaries."""
    if not segments:
        return segments

    merged: list[tuple[int, int]] = [(s.start_offset, s.end_offset) for s in segments]

    # Merge segments smaller than min_chars (don't cross structure markers)
    changed = True
    while changed and len(merged) > 1:
        changed = False
        new_merged: list[tuple[int, int]] = []
        i = 0
        while i < len(merged):
            start, end = merged[i]
            span_len = end - start
            if span_len < min_chars and i + 1 < len(merged):
                next_start, next_end = merged[i + 1]
                combined = next_end - start
                # Don't merge across structure boundary between segments
                cross_structure = any(start < ss < next_start for ss in structure_starts)
                if not cross_structure and combined <= max_chars:
                    new_merged.append((start, next_end))
                    i += 2
                    changed = True
                    continue
            new_merged.append((start, end))
            i += 1
        merged = new_merged

    # Split oversized segments at sentence boundaries
    split_merged: list[tuple[int, int]] = []
    for start, end in merged:
        span_len = end - start
        if span_len <= max_chars:
            split_merged.append((start, end))
            continue
        cursor = start
        while cursor < end:
            remaining = end - cursor
            if remaining <= max_chars:
                split_merged.append((cursor, end))
                break
            window_end = min(cursor + max_chars, end)
            target_end = min(cursor + target_chars, end)
            split_at = _find_split_point(
                text,
                cursor,
                target_end,
                window_end,
                structure_starts,
                min_chars=min_chars,
            )
            if split_at <= cursor:
                split_at = window_end
            split_merged.append((cursor, split_at))
            cursor = split_at

    return [
        _make_segment(i, text, start, end)
        for i, (start, end) in enumerate(split_merged)
    ]


def _assert_coverage(text: str, segments: list[ChunkSegment]) -> None:
    """Verify segments fully cover text without gaps or overlaps."""
    if not segments:
        return
    assert segments[0].start_offset == 0, "First segment must start at 0"
    for i in range(len(segments) - 1):
        assert segments[i].end_offset == segments[i + 1].start_offset, (
            f"Gap between segment {i} and {i + 1}"
        )
    assert segments[-1].end_offset == len(text), "Last segment must end at text length"
    joined = "".join(s.raw_text for s in segments)
    assert joined == text, "Segment concatenation must equal original text"
