"""Text chunker — structure-aware splitting with semantic boundaries."""

from __future__ import annotations

import re
from dataclasses import dataclass

from lumina_core.config import (
    CHUNK_MAX_CHARS,
    CHUNK_MIN_CHARS,
    CHUNK_TARGET_CHARS,
    SEMANTIC_TOPIC_SHIFT_THRESHOLD,
    ChunkBudget,
)
from lumina_core.chunker.embeddings import RuleBoundaryScorer
from lumina_core.chunker.semantic import PairScorer, adaptive_merge, atomize_text

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
    scorer: PairScorer | None = None,
    topic_shift_threshold: float = SEMANTIC_TOPIC_SHIFT_THRESHOLD,
    document_map: list | None = None,
    structure_roles: list | None = None,
) -> list[ChunkSegment]:
    """Split text by structural completeness, local density, and topic changes."""
    if budget is not None:
        target_chars = budget.target_chars
        max_chars = budget.max_chars
        min_chars = budget.min_chars

    text = text.strip()
    if not text:
        return []

    from lumina_core.chunker.document_map import assign_roles_to_atoms, heuristic_document_map

    atoms = atomize_text(
        text,
        target_chars=target_chars,
        max_chars=max_chars,
    )
    units = document_map if document_map is not None else heuristic_document_map(
        text,
        structure_roles=structure_roles,
    )
    atoms = assign_roles_to_atoms(atoms, units)
    spans = adaptive_merge(
        text,
        atoms,
        scorer=scorer or RuleBoundaryScorer(),
        target_chars=target_chars,
        max_chars=max_chars,
        min_chars=min_chars,
        topic_shift_threshold=topic_shift_threshold,
    )
    segments = [
        _make_segment(index, text, start, end)
        for index, (start, end) in enumerate(spans)
    ]
    _assert_coverage(text, segments)
    return segments


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
