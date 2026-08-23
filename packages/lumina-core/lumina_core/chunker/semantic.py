"""Semantic atoms, local style detection, and adaptive adjacent merging."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import Enum, IntEnum
from typing import Protocol

from lumina_core.chunker.roles import DocumentRole, role_families_differ


class TextStyle(str, Enum):
    PROSE = "prose"
    CLASSICAL = "classical"
    POETRY = "poetry"
    LIST = "list"
    HEADING = "heading"


class BoundaryStrength(IntEnum):
    FORBIDDEN = 0
    NORMAL = 1
    STRONG = 2
    HARD = 3


@dataclass(frozen=True)
class TextAtom:
    start: int
    end: int
    text: str
    style: TextStyle
    boundary_before: BoundaryStrength
    role: DocumentRole = DocumentRole.BODYMATTER

    @property
    def content_chars(self) -> int:
        return len(re.sub(r"\s+", "", self.text))


class PairScorer(Protocol):
    def score_pairs(self, pairs: list[tuple[str, str]]) -> list[float]:
        """Return topic novelty in [0, 1] for every adjacent pair."""


_STRUCTURE_LINE = re.compile(
    r"^(?:## \[(?:§.+|p\.\d+(?:\s+无文本)?)\]|"
    r"第[零一二三四五六七八九十百千\d]+[章节篇回].*|§\s*.+|#{1,6}\s+.+)$"
)
_LIST_LINE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)、]\s*|[一二三四五六七八九十]+、)")
# True sentence ends. Latin .!? only count before whitespace/end (not 3.14 / Mr.).
_SENTENCE_END = re.compile(
    r'(?:[。！？…][」』"\'\)\]】]*|(?<!\d)(?<![A-Z][a-z])[.!?][」』"\'\)\]】]*(?=\s|$))'
)
_CLAUSE_END = re.compile(r"[；，、;,]")
_BLANK_LINE = re.compile(r"\n[ \t]*\n+")
_WHITESPACE_RUN = re.compile(r"\s+")
_HAN = re.compile(r"[\u3400-\u9fff]")
_CLASSICAL_TERMS = re.compile(
    r"之|乎|者|也|矣|焉|兮|哉|曰|其|乃|故|若|则|于|而|以|为|弗|未几|既而|是以"
)
_MODERN_TERMS = re.compile(r"我们|你们|他们|这个|那个|因为|所以|但是|已经|可以|进行|问题")
SEGMENT_MIN_CHARS = 500


def detect_style(value: str) -> TextStyle:
    """Classify a local block; uncertainty deliberately falls back to prose."""
    stripped = value.strip()
    if not stripped:
        return TextStyle.PROSE
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    if len(lines) == 1 and _looks_like_heading(lines[0]):
        return TextStyle.HEADING
    if lines and sum(bool(_LIST_LINE.match(line)) for line in lines) / len(lines) >= 0.5:
        return TextStyle.LIST
    if len(lines) >= 3:
        lengths = [len(re.sub(r"\s+", "", line)) for line in lines]
        if sum(length <= 32 for length in lengths) / len(lengths) >= 0.8:
            return TextStyle.POETRY

    han_count = len(_HAN.findall(stripped))
    if han_count >= 24 and not _MODERN_TERMS.search(stripped):
        term_count = len(_CLASSICAL_TERMS.findall(stripped))
        sentences = [s for s in _SENTENCE_END.split(stripped) if s.strip()]
        avg_sentence = han_count / max(1, len(sentences))
        if term_count / han_count >= 0.035 and avg_sentence <= 45:
            return TextStyle.CLASSICAL
    return TextStyle.PROSE


def atomize_text(
    text: str,
    *,
    target_chars: int,
    max_chars: int,
) -> list[TextAtom]:
    """Split into contiguous structural atoms without losing separators."""
    if not text:
        return []

    starts = {0, len(text)}
    # Blank lines define natural blocks; separators stay attached to the prior atom.
    starts.update(match.end() for match in re.finditer(r"\n[ \t]*\n+", text))
    # Strong source/chapter markers must start their own atom.
    offset = 0
    for line in text.splitlines(keepends=True):
        if _STRUCTURE_LINE.match(line.strip()):
            starts.add(offset)
        offset += len(line)

    ordered = sorted(starts)
    atoms: list[TextAtom] = []
    previous_was_heading = False
    in_toc = False
    for start, end in zip(ordered, ordered[1:]):
        if end <= start:
            continue
        value = text[start:end]
        style = detect_style(value)
        stripped_first = value.strip().splitlines()[0] if value.strip() else ""
        if stripped_first.startswith("## [§") and "目录" in stripped_first:
            in_toc = True
        elif stripped_first.startswith("## [§") and "目录" not in stripped_first:
            in_toc = False
        if in_toc:
            # EPUB TOCs often contain one synthetic marker and chapter-like line
            # per tiny entry; none of those are real chapter boundaries.
            boundary = BoundaryStrength.STRONG
        elif _STRUCTURE_LINE.match(stripped_first):
            boundary = BoundaryStrength.HARD
        elif previous_was_heading:
            boundary = BoundaryStrength.FORBIDDEN
        else:
            boundary = BoundaryStrength.STRONG

        preferred_chars = _preferred_atom_chars(style, target_chars, max_chars)
        pieces = _split_oversized_span(
            text,
            start,
            end,
            preferred_chars=preferred_chars,
            max_chars=max_chars,
        )
        for piece_index, (piece_start, piece_end) in enumerate(pieces):
            piece_text = text[piece_start:piece_end]
            piece_style = detect_style(piece_text)
            piece_boundary = boundary if piece_index == 0 else BoundaryStrength.NORMAL
            atoms.append(
                TextAtom(
                    start=piece_start,
                    end=piece_end,
                    text=piece_text,
                    style=piece_style,
                    boundary_before=piece_boundary,
                )
            )
        previous_was_heading = style is TextStyle.HEADING

    if atoms:
        first = atoms[0]
        atoms[0] = TextAtom(
            start=first.start,
            end=first.end,
            text=first.text,
            style=first.style,
            boundary_before=BoundaryStrength.HARD,
        )
    return atoms


def adaptive_merge(
    text: str,
    atoms: list[TextAtom],
    *,
    scorer: PairScorer,
    target_chars: int,
    max_chars: int,
    min_chars: int,
    topic_shift_threshold: float,
) -> list[tuple[int, int]]:
    """Merge adjacent atoms until semantic richness or a meaningful boundary wins."""
    if not atoms:
        return []
    pairs = [(atoms[i - 1].text, atoms[i].text) for i in range(1, len(atoms))]
    novelty = scorer.score_pairs(pairs) if pairs else []
    if len(novelty) != len(pairs):
        novelty = [0.0] * len(pairs)

    spans: list[tuple[int, int]] = []
    group_start = atoms[0].start
    group_end = atoms[0].end
    effective_size = _information_size(atoms[0])
    group_style = atoms[0].style

    for i, atom in enumerate(atoms[1:], start=1):
        boundary = atom.boundary_before
        pair_novelty = novelty[i - 1]
        next_length = atom.end - group_start
        enough_evidence = min(atoms[i - 1].content_chars, atom.content_chars) >= 60
        topic_shift = (
            boundary >= BoundaryStrength.STRONG
            and enough_evidence
            and pair_novelty >= topic_shift_threshold
        )
        complete_poem = group_style is TextStyle.POETRY and boundary >= BoundaryStrength.STRONG
        rich_enough = effective_size >= target_chars and boundary >= BoundaryStrength.NORMAL
        must_cut = boundary is BoundaryStrength.HARD or next_length > max_chars
        should_cut = must_cut or topic_shift or complete_poem or rich_enough
        role_hard = role_families_differ(atoms[i - 1].role, atom.role)
        if role_hard:
            must_cut = True
            should_cut = True

        # A heading owns its first body block unless the model hard limit makes that impossible.
        if (
            boundary is BoundaryStrength.FORBIDDEN
            and next_length <= max_chars
            and not role_hard
        ):
            should_cut = False
        # The 500-char floor applies inside a role family. Role changes (序 vs 正文)
        # are allowed to produce shorter segments.
        if (
            not role_hard
            and group_end - group_start < min(SEGMENT_MIN_CHARS, max_chars)
            and next_length <= max_chars
        ):
            should_cut = False

        if should_cut and group_end > group_start:
            spans.append((group_start, group_end))
            group_start = atom.start
            effective_size = 0.0
            group_style = atom.style

        group_end = atom.end
        effective_size += _information_size(atom)
        if group_style in (TextStyle.HEADING, TextStyle.PROSE):
            group_style = atom.style if atom.style in (TextStyle.CLASSICAL, TextStyle.POETRY) else group_style

    spans.append((group_start, group_end))
    spans = _merge_noise_fragments(
        spans,
        atoms,
        max_chars=max_chars,
        min_chars=min_chars,
    )
    return _enforce_minimum_spans(
        spans,
        atoms,
        text=text,
        text_length=len(text),
        max_chars=max_chars,
    )


def _information_size(atom: TextAtom) -> float:
    multiplier = {
        TextStyle.PROSE: 1.0,
        TextStyle.HEADING: 0.2,
        TextStyle.LIST: 1.2,
        TextStyle.CLASSICAL: 2.4,
        TextStyle.POETRY: 3.0,
    }[atom.style]
    return atom.content_chars * multiplier


def _role_hard_starts(atoms: list[TextAtom]) -> set[int]:
    starts: set[int] = set()
    for index in range(1, len(atoms)):
        if role_families_differ(atoms[index - 1].role, atoms[index].role):
            starts.add(atoms[index].start)
    return starts


def _preferred_atom_chars(
    style: TextStyle,
    target_chars: int,
    max_chars: int,
) -> int:
    if style in (TextStyle.POETRY, TextStyle.HEADING):
        return max_chars
    multiplier = {
        TextStyle.PROSE: 1.0,
        TextStyle.LIST: 1.2,
        TextStyle.CLASSICAL: 2.4,
    }.get(style, 1.0)
    return min(max_chars, max(120, int(target_chars / multiplier)))


def _ends_with_sentence(value: str) -> bool:
    stripped = value.rstrip(" \t")
    if not stripped:
        return False
    for match in _SENTENCE_END.finditer(stripped):
        if match.end() == len(stripped):
            return True
    return False


def _paragraph_cut_offsets(text: str, start: int, limit: int) -> list[int]:
    """Paragraph cuts in (start, limit]. Blank lines, or a newline after a sentence."""
    if limit <= start:
        return []
    offsets: set[int] = set()
    window = text[start:limit]
    for match in _BLANK_LINE.finditer(window):
        pos = start + match.end()
        if start < pos <= limit:
            offsets.add(pos)
    for match in re.finditer(r"\n", window):
        pos = start + match.end()
        if not (start < pos <= limit):
            continue
        line_end = start + match.start()
        line_start = text.rfind("\n", 0, line_end)
        line = text[(line_start + 1 if line_start != -1 else 0) : line_end]
        if _ends_with_sentence(line):
            offsets.add(pos)
    return sorted(offsets)


def _sentence_cut_offsets(text: str, start: int, limit: int) -> list[int]:
    if limit <= start:
        return []
    window = text[start:limit]
    offsets: list[int] = []
    for match in _SENTENCE_END.finditer(window):
        pos = start + match.end()
        if start < pos <= limit:
            offsets.append(pos)
    return offsets


def _weak_cut_offsets(text: str, start: int, limit: int) -> list[int]:
    if limit <= start:
        return []
    window = text[start:limit]
    offsets: set[int] = set()
    for match in _CLAUSE_END.finditer(window):
        pos = start + match.end()
        if start < pos <= limit:
            offsets.add(pos)
    for match in _WHITESPACE_RUN.finditer(window):
        pos = start + match.end()
        if start < pos <= limit:
            offsets.add(pos)
    return sorted(offsets)


def _best_cut_offset(
    text: str,
    cursor: int,
    *,
    preferred_chars: int,
    max_chars: int,
    end: int,
) -> int | None:
    """Pick a cut after cursor. Prefer paragraph, then sentence; never mid-sentence if one exists."""
    remaining = end - cursor
    if remaining <= preferred_chars:
        return None
    preferred_limit = min(cursor + preferred_chars, end)
    hard_limit = min(cursor + max_chars, end)

    paragraph_preferred = _paragraph_cut_offsets(text, cursor, preferred_limit)
    if paragraph_preferred:
        return paragraph_preferred[-1]
    sentence_preferred = _sentence_cut_offsets(text, cursor, preferred_limit)
    if sentence_preferred:
        return sentence_preferred[-1]

    paragraph_hard = _paragraph_cut_offsets(text, cursor, hard_limit)
    if paragraph_hard:
        return paragraph_hard[-1]
    sentence_hard = _sentence_cut_offsets(text, cursor, hard_limit)
    if sentence_hard:
        return sentence_hard[-1]

    if remaining <= max_chars:
        return None

    weak = _weak_cut_offsets(text, cursor, hard_limit)
    if weak:
        return weak[-1]
    if hard_limit > cursor:
        return hard_limit
    return None


def _pick_rebalance_split(
    text: str,
    *,
    combined_start: int,
    combined_end: int,
    lower: int,
    upper: int,
    target: int,
    max_chars: int,
    atom_starts: list[int] | None = None,
) -> int:
    """Split a combined span without cutting mid-sentence when a terminator exists."""

    def closest(candidates: list[int]) -> int:
        return min(candidates, key=lambda point: (abs(point - target), point))

    def in_window(offsets: list[int], lo: int, hi: int) -> list[int]:
        return [point for point in offsets if lo <= point <= hi]

    paragraphs = _paragraph_cut_offsets(text, combined_start, combined_end)
    sentences = _sentence_cut_offsets(text, combined_start, combined_end)
    atoms = [point for point in (atom_starts or []) if combined_start < point < combined_end]
    weak = _weak_cut_offsets(text, combined_start, combined_end)

    if lower <= upper:
        for group in (paragraphs, sentences, atoms):
            hits = in_window(group, lower, upper)
            if hits:
                return closest(hits)
        hits = in_window(weak, lower, upper)
        if hits:
            return closest(hits)

    # Semantic cuts outside the floor window beat a mid-sentence arithmetic cut.
    # Do not reuse atom starts here: they are often the original failing boundary.
    wide_lo = max(combined_start + 1, combined_end - max_chars)
    wide_hi = min(combined_end - 1, combined_start + max_chars)
    if wide_lo <= wide_hi:
        for group in (paragraphs, sentences):
            hits = in_window(group, wide_lo, wide_hi)
            if hits:
                return closest(hits)
        hits = in_window(weak, wide_lo, wide_hi)
        if hits:
            return closest(hits)

    if lower <= upper:
        return min(max(target, lower), upper)
    return min(max(target, combined_start + 1), combined_end - 1)


def _merge_noise_fragments(
    spans: list[tuple[int, int]],
    atoms: list[TextAtom],
    *,
    max_chars: int,
    min_chars: int,
) -> list[tuple[int, int]]:
    """Merge only genuinely tiny metadata/TOC fragments, never semantic blocks."""
    if len(spans) < 2:
        return spans
    hard_starts = {
        atom.start for atom in atoms if atom.boundary_before is BoundaryStrength.HARD
    }
    hard_starts |= _role_hard_starts(atoms)
    atom_starts = sorted({atom.start for atom in atoms})
    balanced: list[tuple[int, int]] = []
    for start, end in spans:
        if (
            balanced
            and end - start < min_chars
            and start not in hard_starts
            and any("§目录" in atom.text for atom in atoms if balanced[-1][0] <= atom.start < end)
        ):
            previous_start, _ = balanced[-1]
            candidates = [
                point
                for point in atom_starts
                if previous_start + min_chars <= point <= end - min_chars
                and point - previous_start <= max_chars
                and end - point <= max_chars
            ]
            if candidates:
                split_at = min(candidates, key=lambda point: abs(point - (previous_start + end) / 2))
                balanced[-1] = (previous_start, split_at)
                start = split_at
        balanced.append((start, end))

    out: list[tuple[int, int]] = []
    for start, end in balanced:
        synthetic_metadata = any(
            atom.text.lstrip().startswith("## [")
            for atom in atoms
            if start <= atom.start < end
        )
        tiny = (
            synthetic_metadata
            and end - start < min(120, max(24, min_chars // 10))
        )
        if (
            tiny
            and out
            and start not in hard_starts
            and end - out[-1][0] <= max_chars
        ):
            previous_start, _ = out[-1]
            out[-1] = (previous_start, end)
        else:
            out.append((start, end))
    return out


def _enforce_minimum_spans(
    spans: list[tuple[int, int]],
    atoms: list[TextAtom],
    *,
    text: str,
    text_length: int,
    max_chars: int,
) -> list[tuple[int, int]]:
    """Guarantee the 500-char floor by merging or rebalancing the final tail."""
    floor = min(SEGMENT_MIN_CHARS, max_chars)
    if text_length < floor or len(spans) < 2:
        return spans
    role_hard_starts = _role_hard_starts(atoms)
    atom_starts = [atom.start for atom in atoms]

    out = list(spans)
    i = 0
    while i < len(out):
        start, end = out[i]
        if end - start >= floor:
            i += 1
            continue

        neighbor = i - 1 if i > 0 else i + 1
        left_index, right_index = sorted((i, neighbor))
        later_start = out[right_index][0]
        if later_start in role_hard_starts:
            i += 1
            continue
        combined_start = out[left_index][0]
        combined_end = out[right_index][1]
        combined_length = combined_end - combined_start
        if combined_length <= max_chars:
            out[left_index : right_index + 1] = [(combined_start, combined_end)]
            i = max(0, left_index - 1)
            continue

        lower = max(combined_start + floor, combined_end - max_chars)
        upper = min(combined_start + max_chars, combined_end - floor)
        if lower <= upper:
            original_boundary = out[right_index][0]
            split_at = _pick_rebalance_split(
                text,
                combined_start=combined_start,
                combined_end=combined_end,
                lower=lower,
                upper=upper,
                target=original_boundary,
                max_chars=max_chars,
                atom_starts=atom_starts,
            )
            if combined_start < split_at < combined_end:
                replacement = [
                    (combined_start, split_at),
                    (split_at, combined_end),
                ]
                if replacement != out[left_index : right_index + 1]:
                    out[left_index : right_index + 1] = replacement
                    i = max(0, left_index - 1)
                    continue
            i += 1
            continue

        # Two adjacent spans may not contain enough text for two 500-char
        # results. Expand the local window and repartition it at natural points.
        expanded_left = left_index
        expanded_right = right_index
        while True:
            expanded_start = out[expanded_left][0]
            expanded_end = out[expanded_right][1]
            expanded_length = expanded_end - expanded_start
            part_count = (expanded_length + max_chars - 1) // max_chars
            if part_count <= expanded_length // floor:
                break
            if expanded_left > 0:
                expanded_left -= 1
            elif expanded_right + 1 < len(out):
                expanded_right += 1
            else:
                part_count = 1
                break
        replacement = _balanced_partition(
            text,
            out[expanded_left][0],
            out[expanded_right][1],
            part_count=part_count,
            atoms=atoms,
            floor=floor,
            max_chars=max_chars,
        )
        current = out[expanded_left : expanded_right + 1]
        if replacement == current:
            i += 1
            continue
        out[expanded_left : expanded_right + 1] = replacement
        i = max(0, expanded_left - 1)
    return out


def _balanced_partition(
    text: str,
    start: int,
    end: int,
    *,
    part_count: int,
    atoms: list[TextAtom],
    floor: int,
    max_chars: int,
) -> list[tuple[int, int]]:
    if part_count <= 1:
        return [(start, end)]
    atom_starts = [atom.start for atom in atoms if start < atom.start < end]
    natural_points = set(atom_starts)
    natural_points.update(
        point for point in _paragraph_cut_offsets(text, start, end) if start < point < end
    )
    natural_points.update(
        point for point in _sentence_cut_offsets(text, start, end) if start < point < end
    )

    boundaries = [start]
    cursor = start
    for index in range(1, part_count):
        remaining_parts = part_count - index
        lower = max(cursor + floor, end - remaining_parts * max_chars)
        upper = min(cursor + max_chars, end - remaining_parts * floor)
        target = start + round((end - start) * index / part_count)
        candidates = [point for point in natural_points if lower <= point <= upper]
        if candidates:
            boundary = min(candidates, key=lambda point: abs(point - target))
        else:
            boundary = _pick_rebalance_split(
                text,
                combined_start=cursor,
                combined_end=end,
                lower=lower,
                upper=upper,
                target=target,
                max_chars=max_chars,
                atom_starts=atom_starts,
            )
        if boundary <= cursor:
            later = [point for point in natural_points if cursor < point < end]
            if not later:
                later = [
                    point
                    for point in _weak_cut_offsets(text, cursor, end)
                    if cursor < point < end
                ]
            if later:
                boundary = min(later)
            elif end - cursor > max_chars:
                boundary = min(cursor + max_chars, end)
            else:
                break
        boundaries.append(boundary)
        cursor = boundary
    boundaries.append(end)
    return list(zip(boundaries, boundaries[1:]))


def _looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if _STRUCTURE_LINE.match(stripped):
        return True
    if not stripped or len(stripped) > 40:
        return False
    if _SENTENCE_END.search(stripped):
        return False
    return bool(re.fullmatch(r"[\w\u3400-\u9fff《》〈〉·：:—\- ]+", stripped))


def _split_oversized_span(
    text: str,
    start: int,
    end: int,
    *,
    preferred_chars: int,
    max_chars: int,
) -> list[tuple[int, int]]:
    pieces: list[tuple[int, int]] = []
    cursor = start
    while end - cursor > preferred_chars:
        split_at = _best_cut_offset(
            text,
            cursor,
            preferred_chars=preferred_chars,
            max_chars=max_chars,
            end=end,
        )
        if split_at is None or split_at <= cursor or split_at >= end:
            break
        pieces.append((cursor, split_at))
        cursor = split_at
    if cursor < end:
        pieces.append((cursor, end))
    return pieces
