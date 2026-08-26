"""Manual adjacent-segment boundary moves with atom/sentence snapping."""

from __future__ import annotations

from dataclasses import dataclass

from lumina_core.chunker.chunker import _chapter_at, _page_range_in, index_text_markers
from lumina_core.chunker.semantic import (
    BoundaryStrength,
    TextStyle,
    _SENTENCE_END,
    atomize_text,
)
from lumina_core.config import CHUNK_MAX_CHARS, CHUNK_TARGET_CHARS


class BoundaryError(ValueError):
    """User-facing validation failure for a boundary move."""


@dataclass(frozen=True)
class BoundaryCandidate:
    offset: int
    kind: str


@dataclass(frozen=True)
class BoundaryMove:
    left_text: str
    right_text: str
    snapped_offset: int
    left_chapter: str | None
    right_chapter: str | None
    left_page_range: str | None
    right_page_range: str | None
    unchanged: bool

    @property
    def left_char_count(self) -> int:
        return len(self.left_text)

    @property
    def right_char_count(self) -> int:
        return len(self.right_text)

    @property
    def oversized(self) -> bool:
        return (
            self.left_char_count > CHUNK_MAX_CHARS
            or self.right_char_count > CHUNK_MAX_CHARS
        )


def segment_anchor_label(
    idx: int, chapter: str | None, page_range: str | None
) -> str:
    anchor = f"段 {idx + 1}"
    if chapter:
        anchor = f"{chapter} · 段 {idx + 1}"
    if page_range:
        anchor = f"{anchor} · {page_range}"
    return f"〔{anchor}〕"


def list_cut_offsets(
    concat: str,
    *,
    current_offset: int | None = None,
    target_chars: int = CHUNK_TARGET_CHARS,
    max_chars: int = CHUNK_MAX_CHARS,
) -> list[BoundaryCandidate]:
    """Return legal cut offsets inside concat, excluding the ends."""
    if not concat:
        return []

    by_offset: dict[int, str] = {}
    atoms = atomize_text(
        concat,
        target_chars=target_chars,
        max_chars=max_chars,
    )
    for atom in atoms[1:]:
        if atom.start <= 0 or atom.start >= len(concat):
            continue
        by_offset[atom.start] = _kind_for_atom(atom.boundary_before, atom.style)

    for match in _SENTENCE_END.finditer(concat):
        end = match.end()
        if 0 < end < len(concat):
            by_offset.setdefault(end, "sentence")

    if current_offset is not None and 0 < current_offset < len(concat):
        by_offset.setdefault(current_offset, "current")

    return [
        BoundaryCandidate(offset=offset, kind=kind)
        for offset, kind in sorted(by_offset.items())
    ]


def snap_cut_offset(
    concat: str,
    offset: int,
    *,
    current_offset: int | None = None,
    target_chars: int = CHUNK_TARGET_CHARS,
    max_chars: int = CHUNK_MAX_CHARS,
) -> int:
    candidates = list_cut_offsets(
        concat,
        current_offset=current_offset,
        target_chars=target_chars,
        max_chars=max_chars,
    )
    if not candidates:
        raise BoundaryError("这两段之间没有可调整的语义边界")
    return min(candidates, key=lambda item: (abs(item.offset - offset), item.offset)).offset


def apply_cut(
    left_text: str,
    right_text: str,
    left_char_count: int,
    *,
    target_chars: int = CHUNK_TARGET_CHARS,
    max_chars: int = CHUNK_MAX_CHARS,
) -> BoundaryMove:
    concat = f"{left_text}{right_text}"
    if not concat:
        raise BoundaryError("这两段没有可调整的正文")
    if left_char_count <= 0 or left_char_count >= len(concat):
        raise BoundaryError("调整后两侧都必须保留正文")
    current_offset = len(left_text)
    snapped = snap_cut_offset(
        concat,
        left_char_count,
        current_offset=current_offset,
        target_chars=target_chars,
        max_chars=max_chars,
    )
    new_left = concat[:snapped]
    new_right = concat[snapped:]
    if not new_left or not new_right:
        raise BoundaryError("调整后两侧都必须保留正文")
    if new_left + new_right != concat:
        raise BoundaryError("调整后必须覆盖原有正文")
    markers = index_text_markers(concat)
    return BoundaryMove(
        left_text=new_left,
        right_text=new_right,
        snapped_offset=snapped,
        left_chapter=_chapter_at(concat, 0, markers=markers),
        right_chapter=_chapter_at(concat, snapped, markers=markers),
        left_page_range=_page_range_in(concat, 0, snapped, markers=markers),
        right_page_range=_page_range_in(concat, snapped, len(concat), markers=markers),
        unchanged=snapped == current_offset,
    )


def remap_note_segment_id(
    quote: str | None,
    original_segment_id: str,
    left_id: str,
    right_id: str,
    new_left: str,
    new_right: str,
) -> str:
    """Keep notes on the side that still contains their quote."""
    trimmed = (quote or "").strip()
    if not trimmed:
        return original_segment_id
    in_left = trimmed in new_left
    in_right = trimmed in new_right
    if in_left and not in_right:
        return left_id
    if in_right and not in_left:
        return right_id
    return original_segment_id


def _kind_for_atom(boundary: BoundaryStrength, style: TextStyle) -> str:
    if style is TextStyle.HEADING or boundary is BoundaryStrength.HARD:
        return "heading"
    if boundary is BoundaryStrength.STRONG:
        return "paragraph"
    return "sentence"
