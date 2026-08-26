"""Text chunker — structure tree first, then whole-paragraph packing inside chapters."""

from __future__ import annotations

import bisect
import threading
from dataclasses import dataclass

from lumina_core.config import (
    CHUNK_MAX_CHARS,
    CHUNK_MIN_CHARS,
    CHUNK_TARGET_CHARS,
    SEMANTIC_TOPIC_SHIFT_THRESHOLD,
    ChunkBudget,
)
from lumina_core.chunker.coop import (
    LARGE_ATOM_EMBED_LIMIT,
    LARGE_TEXT_EMBED_CHARS,
    GilYielder,
    coerce_char_progress,
    iter_text_lines,
)
from lumina_core.chunker.embeddings import RuleBoundaryScorer
from lumina_core.chunker.markers import (
    PAGE_MARKER,
    bare_chapter_title,
    match_bare_chapter,
    may_be_hash_heading_line,
)
from lumina_core.chunker.semantic import PairScorer, adaptive_merge, atomize_text
from lumina_core.chunker.tree import DocumentNode, build_document_tree, chapter_path_at


@dataclass(frozen=True)
class ChunkSegment:
    index: int
    raw_text: str
    start_offset: int
    end_offset: int
    chapter: str | None = None
    page_range: str | None = None


@dataclass(frozen=True)
class TextMarkers:
    """One-pass page/chapter offsets. Segment assembly must not rescan the book."""

    page_offsets: tuple[int, ...]
    page_numbers: tuple[int, ...]
    chapter_offsets: tuple[int, ...]
    chapter_titles: tuple[str, ...]


def index_text_markers(
    text: str,
    yielder: GilYielder | None = None,
) -> TextMarkers:
    """Scan PAGE_MARKER and BARE_CHAPTER once, line by line. Never finditer the book."""
    coop = yielder or GilYielder()
    page_offsets: list[int] = []
    page_numbers: list[int] = []
    chapter_offsets: list[int] = []
    chapter_titles: list[str] = []
    for offset, line in iter_text_lines(text, coop):
        if may_be_hash_heading_line(line):
            page = PAGE_MARKER.match(line)
            if page is not None:
                page_offsets.append(offset)
                page_numbers.append(int(page.group(1)))
                continue
        chapter = match_bare_chapter(line)
        if chapter is not None:
            chapter_offsets.append(offset)
            chapter_titles.append(bare_chapter_title(chapter) or "")
    return TextMarkers(
        page_offsets=tuple(page_offsets),
        page_numbers=tuple(page_numbers),
        chapter_offsets=tuple(chapter_offsets),
        chapter_titles=tuple(chapter_titles),
    )


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
    document_tree: DocumentNode | None = None,
    cancel_event: threading.Event | None = None,
    on_progress=None,
    strip_text: bool = True,
) -> list[ChunkSegment]:
    """Split text by structural completeness, local density, and topic changes."""
    if budget is not None:
        target_chars = budget.target_chars
        max_chars = budget.max_chars
        min_chars = budget.min_chars

    text = text.strip() if strip_text else text
    if not text:
        return []

    from lumina_core.chunker.document_map import assign_roles_to_atoms, heuristic_document_map

    reporter = coerce_char_progress(on_progress)
    yielder = GilYielder(
        cancel_event,
        on_progress=reporter,
        progress_total=len(text),
        progress_message="正在识别结构树…",
    )
    tree = document_tree or build_document_tree(
        text, structure_roles=structure_roles, yielder=yielder
    )
    markers = index_text_markers(text, yielder)
    yielder.set_stage("正在拆分自然段…", reset=False)
    atoms = atomize_text(
        text,
        target_chars=target_chars,
        max_chars=max_chars,
        yielder=yielder,
    )
    units = document_map if document_map is not None else heuristic_document_map(
        text,
        structure_roles=structure_roles,
        yielder=yielder,
    )
    atoms = assign_roles_to_atoms(atoms, units)
    resolved_scorer = scorer or RuleBoundaryScorer()
    if len(atoms) > LARGE_ATOM_EMBED_LIMIT or len(text) > LARGE_TEXT_EMBED_CHARS:
        resolved_scorer = RuleBoundaryScorer()
    yielder.set_stage("正在合并阅读单元…", reset=False)
    spans = adaptive_merge(
        text,
        atoms,
        scorer=resolved_scorer,
        target_chars=target_chars,
        max_chars=max_chars,
        min_chars=min_chars,
        topic_shift_threshold=topic_shift_threshold,
        yielder=yielder,
    )
    yielder.set_stage("正在生成段落…", reset=False)
    segments: list[ChunkSegment] = []
    for index, (start, end) in enumerate(spans):
        segments.append(_make_segment(index, text, start, end, tree, markers))
        yielder.bump(end - start)
    _assert_coverage(text, segments)
    return segments


def rebuild_chunks(
    text: str,
    spans: list[tuple[int, int]],
    *,
    structure_roles: list | None = None,
    document_tree: DocumentNode | None = None,
) -> list[ChunkSegment]:
    tree = document_tree or build_document_tree(text, structure_roles=structure_roles)
    markers = index_text_markers(text)
    segments = [
        _make_segment(index, text, start, end, tree, markers)
        for index, (start, end) in enumerate(spans)
    ]
    _assert_coverage(text, segments)
    return segments


def _make_segment(
    idx: int,
    text: str,
    start: int,
    end: int,
    tree: DocumentNode | None = None,
    markers: TextMarkers | None = None,
) -> ChunkSegment:
    resolved = markers or index_text_markers(text)
    return ChunkSegment(
        index=idx,
        raw_text=text[start:end],
        start_offset=start,
        end_offset=end,
        chapter=_chapter_at(text, start, tree=tree, markers=resolved),
        page_range=_page_range_in(text, start, end, markers=resolved),
    )


def _chapter_at(
    text: str,
    offset: int,
    tree: DocumentNode | None = None,
    markers: TextMarkers | None = None,
) -> str | None:
    """Extract chapter path from the structure tree, falling back to markers."""
    resolved_tree = tree or build_document_tree(text)
    path = chapter_path_at(resolved_tree, offset)
    if path:
        return path if path.startswith("§") else f"§{path}"

    resolved = markers or index_text_markers(text)
    if not resolved.chapter_offsets:
        return None
    index = bisect.bisect_right(resolved.chapter_offsets, offset) - 1
    if index < 0:
        return None
    title = resolved.chapter_titles[index]
    return title or None


def _page_range_in(
    text: str,
    start: int,
    end: int,
    markers: TextMarkers | None = None,
) -> str | None:
    """Build p.N or p.N-M from PDF page markers within [start, end)."""
    resolved = markers or index_text_markers(text)
    if not resolved.page_offsets:
        return None
    index = bisect.bisect_left(resolved.page_offsets, start)
    pages: list[int] = []
    while index < len(resolved.page_offsets) and resolved.page_offsets[index] < end:
        pages.append(resolved.page_numbers[index])
        index += 1
    if not pages:
        return None
    if len(pages) == 1:
        return f"p.{pages[0]}"
    return f"p.{pages[0]}-{pages[-1]}"


def _assert_coverage(text: str, segments: list[ChunkSegment]) -> None:
    """Verify segments fully cover text without losing separators."""
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
