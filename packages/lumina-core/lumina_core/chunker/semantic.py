"""Semantic atoms, local style detection, and adaptive adjacent merging."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import Enum, IntEnum
from typing import Protocol

from lumina_core.chunker.coop import GilYielder, LARGE_ATOM_EMBED_LIMIT, iter_text_lines
from lumina_core.chunker.markers import (
    clean_structure_title,
    is_hard_heading_line,
    is_hash_heading_line,
    is_page_line,
    match_structure_line,
    parse_heading_line,
)
from lumina_core.chunker.roles import DocumentRole, role_families_differ, role_family


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


_LIST_LINE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)、]\s*|[一二三四五六七八九十]+、)")
# True sentence ends. Latin .!? only count before whitespace/end (not 3.14 / Mr.).
_SENTENCE_END = re.compile(
    r'(?:[。！？…][」』"\'\)\]】]*|(?<!\d)(?<![A-Z][a-z])[.!?][」』"\'\)\]】]*(?=\s|$))'
)
_CLAUSE_END = re.compile(r"[；，、;,]")
_BLANK_LINE = re.compile(r"\n[ \t]*\n+")
_WHITESPACE_RUN = re.compile(r"\s+")
# Fullwidth indent starts a new paragraph (TXT novels, some EPUBs).
_LINE_START_INDENT = re.compile(r"(?:^|\n)[ \t]*(　{1,2})(?=\S)")
_LINE_START_INDENT_LINE = re.compile(r"^[ \t]*(　{1,2})(?=\S)")
_INLINE_INDENT = re.compile(r"(?<=[。！？…])[ \t]*(　{2,})(?=\S)")
_HAN = re.compile(r"[\u3400-\u9fff]")
_CLASSICAL_TERMS = re.compile(
    r"之|乎|者|也|矣|焉|兮|哉|曰|其|乃|故|若|则|于|而|以|为|弗|未几|既而|是以"
)
_MODERN_TERMS = re.compile(r"我们|你们|他们|这个|那个|因为|所以|但是|已经|可以|进行|问题")
_STYLE_SAMPLE_CHARS = 800
SEGMENT_MIN_CHARS = 500
SEGMENT_HARD_MIN_CHARS = 200
_CHAPTER_ORDINAL = re.compile(r"第[零一二三四五六七八九十百千\d]+[章节篇回]")


def _segment_floor(min_chars: int, max_chars: int) -> int:
    """Packer soft-window start. A tiny target below 500 wins."""
    return max(1, min(min_chars, max_chars))


def _fragment_floor(min_chars: int, max_chars: int) -> int:
    """Merge only true fragments. Topic-shift cuts may sit between 500 and 0.6T."""
    return min(_segment_floor(min_chars, max_chars), SEGMENT_MIN_CHARS)


def detect_style(value: str) -> TextStyle:
    """Classify a local block; uncertainty deliberately falls back to prose."""
    stripped = value.strip()
    if not stripped:
        return TextStyle.PROSE
    if len(stripped) > _STYLE_SAMPLE_CHARS:
        stripped = stripped[:_STYLE_SAMPLE_CHARS]
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
    yielder: GilYielder | None = None,
) -> list[TextAtom]:
    """Split into contiguous structural atoms without losing separators."""
    if not text:
        return []

    coop = yielder or GilYielder()
    starts = {0, len(text)}
    for offset, line in iter_text_lines(text, coop):
        stripped_line = line.strip()
        if match_structure_line(stripped_line) or is_hard_heading_line(stripped_line):
            starts.add(offset)
    starts.update(_paragraph_cut_offsets(text, 0, len(text), yielder=coop))

    ordered = sorted(starts)
    atoms: list[TextAtom] = []
    previous_was_heading = False
    in_toc = False
    for start, end in zip(ordered, ordered[1:]):
        if end <= start:
            continue
        value = text[start:end]
        if not value.strip() and atoms:
            previous = atoms[-1]
            atoms[-1] = replace(
                previous,
                end=end,
                text=text[previous.start:end],
            )
            continue
        style = detect_style(value)
        stripped_first = value.strip().splitlines()[0] if value.strip() else ""
        parsed = parse_heading_line(stripped_first)
        if parsed is not None and "目录" in parsed[1]:
            in_toc = True
        elif (
            parsed is not None
            and parsed[0] <= 1
            and "目录" not in parsed[1]
            and is_hash_heading_line(stripped_first)
        ):
            # Bare 第N章 lines inside an EPUB TOC are entries, not the next chapter.
            in_toc = False
        if in_toc:
            # EPUB TOCs often contain one synthetic marker and chapter-like line
            # per tiny entry; none of those are real chapter boundaries.
            boundary = BoundaryStrength.STRONG
        elif is_page_line(stripped_first):
            boundary = BoundaryStrength.NORMAL
        elif is_hard_heading_line(stripped_first):
            boundary = BoundaryStrength.HARD
        elif parsed is not None:
            boundary = BoundaryStrength.STRONG
        elif previous_was_heading:
            boundary = BoundaryStrength.FORBIDDEN
        else:
            boundary = BoundaryStrength.STRONG

        # Never pre-cut at the reading target. Only split atoms that exceed hard_max.
        if end - start > max_chars:
            pieces = _split_oversized_span(
                text,
                start,
                end,
                preferred_chars=max_chars,
                max_chars=max_chars,
                yielder=coop,
            )
        else:
            pieces = [(start, end)]
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
        coop.bump(end - start)

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
    yielder: GilYielder | None = None,
) -> list[tuple[int, int]]:
    """Pack whole paragraphs until max_chars; topic shift may stop early at a paragraph."""
    if not atoms:
        return []
    coop = yielder or GilYielder()
    floor = _segment_floor(min_chars, max_chars)
    novelty = [0.0] * max(0, len(atoms) - 1)
    # Huge books: skip pair scoring (embedding and lexical). Pack by structure + max_chars.
    if len(atoms) <= LARGE_ATOM_EMBED_LIMIT:
        score_pairs: list[tuple[str, str]] = []
        score_at: list[int] = []
        for i in range(1, len(atoms)):
            if atoms[i].boundary_before >= BoundaryStrength.STRONG:
                score_pairs.append((atoms[i - 1].text, atoms[i].text))
                score_at.append(i - 1)
            if i % 256 == 0:
                coop.bump(256)
        scored = scorer.score_pairs(score_pairs) if score_pairs else []
        coop.bump(len(atoms))
        if len(scored) == len(score_at):
            for index, value in zip(score_at, scored):
                novelty[index] = value
    else:
        coop.bump(len(atoms))

    spans: list[tuple[int, int]] = []
    group_start = atoms[0].start
    group_end = atoms[0].end
    effective_size = _information_size(atoms[0])
    group_style = atoms[0].style
    group_chapter_key = _body_chapter_key(atoms[0])

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
        section_break = boundary >= BoundaryStrength.STRONG and atom.style is TextStyle.HEADING
        chapter_hard = boundary is BoundaryStrength.HARD
        chapter_like = _bodymatter_chapter_atom(atom)
        incoming_key = _body_chapter_key(atom)
        same_chapter_heading = (
            incoming_key is not None
            and group_chapter_key is not None
            and incoming_key == group_chapter_key
        )
        new_chapter = (chapter_hard or chapter_like) and not same_chapter_heading
        role_hard = role_families_differ(atoms[i - 1].role, atom.role)
        must_cut = new_chapter or role_hard or next_length > max_chars
        group_chars = group_end - group_start
        in_soft_window = group_chars >= floor
        should_cut = must_cut
        if in_soft_window:
            if topic_shift or complete_poem or section_break:
                should_cut = True
            elif (
                group_style in (TextStyle.CLASSICAL, TextStyle.POETRY)
                and effective_size >= target_chars
                and boundary >= BoundaryStrength.STRONG
            ):
                should_cut = True
        elif (
            topic_shift
            and group_chars >= min(SEGMENT_MIN_CHARS, floor)
            and next_length <= max_chars
        ):
            # Distinct topics may split below the 60% budget, never below 500
            # unless the user asked for a smaller min.
            should_cut = True

        # A heading owns its first body block unless the model hard limit makes that impossible.
        # Duplicate same-chapter titles (## [§第一章] + 第一章 …) stay with that body.
        if (
            (boundary is BoundaryStrength.FORBIDDEN or same_chapter_heading)
            and next_length <= max_chars
            and not role_hard
            and not new_chapter
        ):
            should_cut = False
        # Do not swallow the next chapter/role to fill the floor.
        if (
            not role_hard
            and not new_chapter
            and group_chars < floor
            and next_length <= max_chars
            and not (
                topic_shift and group_chars >= min(SEGMENT_MIN_CHARS, floor)
            )
        ):
            should_cut = False

        if should_cut and group_end > group_start:
            spans.append((group_start, group_end))
            group_start = atom.start
            effective_size = 0.0
            group_style = atom.style
            group_chapter_key = incoming_key

        group_end = atom.end
        effective_size += _information_size(atom)
        if incoming_key is not None:
            group_chapter_key = incoming_key
        if group_style in (TextStyle.HEADING, TextStyle.PROSE):
            group_style = atom.style if atom.style in (TextStyle.CLASSICAL, TextStyle.POETRY) else group_style
        coop.bump(atom.end - atom.start)

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
        min_chars=min_chars,
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


def _atom_first_line(atom: TextAtom) -> str:
    stripped = atom.text.strip()
    if not stripped:
        return ""
    return stripped.splitlines()[0]


def _bodymatter_chapter_atom(atom: TextAtom) -> bool:
    """True for 第N章-like headings in body text, not TOC/front crumbs or ### sections."""
    return (
        role_family(atom.role) == "body"
        and is_hard_heading_line(_atom_first_line(atom))
    )


def _normalize_chapter_key(title: str) -> str:
    stripped = clean_structure_title(title)
    match = _CHAPTER_ORDINAL.search(stripped)
    if match:
        return match.group(0)
    return stripped


def _body_chapter_key(atom: TextAtom) -> str | None:
    first = _atom_first_line(atom)
    if not first or is_page_line(first):
        return None
    if role_family(atom.role) != "body":
        return None
    parsed = parse_heading_line(first)
    if parsed is None or parsed[0] > 1:
        return None
    return _normalize_chapter_key(parsed[1])


def _atom_at_offset(atoms: list[TextAtom], offset: int) -> TextAtom | None:
    for atom in atoms:
        if atom.start == offset:
            return atom
        if atom.start < offset < atom.end:
            return atom
    return None


def _span_chapter_key(atoms: list[TextAtom], start: int, end: int) -> str | None:
    for atom in atoms:
        if atom.end <= start:
            continue
        if atom.start >= end:
            break
        key = _body_chapter_key(atom)
        if key is not None:
            return key
    return None


def _span_opens_body_chapter(atoms: list[TextAtom], start: int) -> bool:
    atom = _atom_at_offset(atoms, start)
    return atom is not None and _body_chapter_key(atom) is not None


def _cross_chapter_starts(atoms: list[TextAtom]) -> set[int]:
    """Role-family changes and a *new* body chapter (not duplicate 第N章 shells)."""
    starts = set(_role_hard_starts(atoms))
    last_key: str | None = None
    first_start = atoms[0].start if atoms else 0
    for atom in atoms:
        key = _body_chapter_key(atom)
        if key is None:
            continue
        if last_key is None:
            if atom.start > first_start:
                starts.add(atom.start)
        elif key != last_key:
            starts.add(atom.start)
        last_key = key
    return starts


def _blocks_same_chapter_merge(
    atoms: list[TextAtom],
    role_hard: set[int],
    later_start: int,
    earlier: tuple[int, int],
) -> bool:
    """True if joining `later_start` onto `earlier` would cross role or chapter."""
    if later_start in role_hard:
        return True
    later_atom = _atom_at_offset(atoms, later_start)
    if later_atom is None:
        return False
    later_key = _body_chapter_key(later_atom)
    if later_key is None:
        return False
    earlier_key = _span_chapter_key(atoms, earlier[0], earlier[1])
    if earlier_key is None:
        return True
    return later_key != earlier_key


def _complete_paragraph_starts(atoms: list[TextAtom]) -> set[int]:
    return {
        atom.start
        for index, atom in enumerate(atoms)
        if index > 0 and atom.boundary_before >= BoundaryStrength.STRONG
    }


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
    stripped = value.rstrip(" \t\r")
    if not stripped:
        return False
    for match in _SENTENCE_END.finditer(stripped):
        if match.end() == len(stripped):
            return True
    return False


def _indent_cut_offsets(text: str, start: int, limit: int) -> list[int]:
    if limit <= start:
        return []
    window = text[start:limit]
    offsets: set[int] = set()
    for pattern in (_LINE_START_INDENT, _INLINE_INDENT):
        for match in pattern.finditer(window):
            pos = start + match.start(1)
            if start < pos <= limit:
                offsets.add(pos)
    return sorted(offsets)


def _paragraph_cut_offsets(
    text: str,
    start: int,
    limit: int,
    yielder: GilYielder | None = None,
) -> list[int]:
    """Paragraph cuts in (start, limit]. Blank lines, sentence-ending newline, indent."""
    if limit <= start:
        return []
    offsets: set[int] = set()
    for match in _BLANK_LINE.finditer(text, start, limit):
        pos = match.end()
        if start < pos <= limit:
            offsets.add(pos)
    line_start = start
    cursor = start
    seen_breaks = 0
    has_cr = text.find("\r", start, limit) != -1
    has_lf = text.find("\n", start, limit) != -1
    while has_cr or has_lf:
        cr = text.find("\r", cursor, limit) if has_cr else -1
        lf = text.find("\n", cursor, limit) if has_lf else -1
        if cr == -1 and lf == -1:
            break
        if cr != -1 and (lf == -1 or cr < lf):
            line_end = cr
            nxt = cr + 1
            if nxt < len(text) and nxt <= limit and text[nxt] == "\n":
                nxt += 1
        else:
            line_end = lf
            nxt = lf + 1
        seen_breaks += 1
        if yielder is not None and seen_breaks % 128 == 0:
            yielder.bump(yielder.every)
        pos = nxt
        if start < pos <= limit:
            line = text[line_start:line_end]
            if _ends_with_sentence(line):
                if not (pos < len(text) and text[pos] in " \t\n\r"):
                    offsets.add(pos)
        line_start = nxt
        cursor = nxt
    if limit - start <= 32_000:
        window = text[start:limit]
        for pattern in (_LINE_START_INDENT, _INLINE_INDENT):
            for match in pattern.finditer(window):
                pos = start + match.start(1)
                if start < pos <= limit:
                    offsets.add(pos)
    else:
        window = text[start:limit]
        for rel, line in iter_text_lines(window, yielder):
            offset = start + rel
            leading = _LINE_START_INDENT_LINE.match(line)
            if leading is not None:
                pos = offset + leading.start(1)
                if start < pos <= limit:
                    offsets.add(pos)
            for match in _INLINE_INDENT.finditer(line):
                pos = offset + match.start(1)
                if start < pos <= limit:
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


def _last_cut_in_windows(offsets: list[int], preferred_limit: int) -> int | None:
    """Last cut at or before preferred, else last cut still within the hard window."""
    if not offsets:
        return None
    preferred = [point for point in offsets if point <= preferred_limit]
    if preferred:
        return preferred[-1]
    return offsets[-1]


def _best_cut_offset(
    text: str,
    cursor: int,
    *,
    preferred_chars: int,
    max_chars: int,
    end: int,
) -> int | None:
    """Chapter/paragraph cuts in the max window beat a closer sentence inside target."""
    remaining = end - cursor
    if remaining <= preferred_chars:
        return None
    preferred_limit = min(cursor + preferred_chars, end)
    hard_limit = min(cursor + max_chars, end)

    paragraph_cut = _last_cut_in_windows(
        _paragraph_cut_offsets(text, cursor, hard_limit),
        preferred_limit,
    )
    if paragraph_cut is not None:
        return paragraph_cut
    sentence_cut = _last_cut_in_windows(
        _sentence_cut_offsets(text, cursor, hard_limit),
        preferred_limit,
    )
    if sentence_cut is not None:
        return sentence_cut

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
    """Keep paragraph-complete splits even when one side is below the floor."""

    def closest(candidates: list[int]) -> int:
        return min(candidates, key=lambda point: (abs(point - target), point))

    def in_window(offsets: list[int], lo: int, hi: int) -> list[int]:
        return [point for point in offsets if lo <= point <= hi]

    def both_fit(point: int) -> bool:
        return (
            combined_start < point < combined_end
            and point - combined_start <= max_chars
            and combined_end - point <= max_chars
        )

    paragraphs = _paragraph_cut_offsets(text, combined_start, combined_end)
    sentences = _sentence_cut_offsets(text, combined_start, combined_end)
    atoms = [point for point in (atom_starts or []) if combined_start < point < combined_end]
    weak = _weak_cut_offsets(text, combined_start, combined_end)

    para_fit = [point for point in paragraphs if both_fit(point)]
    if para_fit:
        return closest(para_fit)

    sent_fit = [point for point in sentences if both_fit(point)]
    if lower <= upper:
        hits = in_window(sent_fit, lower, upper)
        if hits:
            return closest(hits)
        hits = in_window(atoms, lower, upper)
        if hits:
            return closest(hits)
        hits = in_window(weak, lower, upper)
        if hits:
            return closest(hits)
    if sent_fit:
        return closest(sent_fit)

    wide_lo = max(combined_start + 1, combined_end - max_chars)
    wide_hi = min(combined_end - 1, combined_start + max_chars)
    if wide_lo <= wide_hi:
        hits = in_window(weak, wide_lo, wide_hi)
        if hits:
            return closest(hits)

    if lower <= upper:
        return min(max(target, lower), upper)
    return min(max(target, combined_start + 1), combined_end - 1)


def _span_has_toc(atoms: list[TextAtom], start: int, end: int) -> bool:
    return any("§目录" in atom.text for atom in atoms if start <= atom.start < end)


def _merge_noise_fragments(
    spans: list[tuple[int, int]],
    atoms: list[TextAtom],
    *,
    max_chars: int,
    min_chars: int,
) -> list[tuple[int, int]]:
    """Pack TOC/metadata crumbs first, then rebalance leftovers to min_chars."""
    if len(spans) < 2:
        return spans
    hard_starts = _cross_chapter_starts(atoms)
    packed = _pack_synthetic_fragments(
        spans,
        atoms,
        hard_starts=hard_starts,
        max_chars=max_chars,
        min_chars=min_chars,
    )
    return _rebalance_toc_spans(
        packed,
        atoms,
        hard_starts=hard_starts,
        max_chars=max_chars,
        min_chars=min_chars,
    )


def _pack_synthetic_fragments(
    spans: list[tuple[int, int]],
    atoms: list[TextAtom],
    *,
    hard_starts: set[int],
    max_chars: int,
    min_chars: int,
) -> list[tuple[int, int]]:
    tiny_limit = min(120, max(24, min_chars // 10))
    role_hard = _role_hard_starts(atoms)
    out: list[tuple[int, int]] = []
    for start, end in spans:
        length = end - start
        synthetic_metadata = any(
            atom.text.lstrip().startswith("## [")
            for atom in atoms
            if start <= atom.start < end
        )
        follows_toc = bool(out) and _span_has_toc(atoms, out[-1][0], out[-1][1])
        if (
            out
            and (out[-1][1] - out[-1][0]) < SEGMENT_HARD_MIN_CHARS
            and end - out[-1][0] <= max_chars
            and not _blocks_same_chapter_merge(atoms, role_hard, start, out[-1])
        ):
            previous_start, _ = out[-1]
            out[-1] = (previous_start, end)
            continue
        packable = start not in hard_starts and (
            (synthetic_metadata and length < tiny_limit)
            or (_span_has_toc(atoms, start, end) and length < min_chars)
            or (follows_toc and length < tiny_limit)
        )
        if packable and out and end - out[-1][0] <= max_chars:
            previous_start, _ = out[-1]
            out[-1] = (previous_start, end)
        else:
            out.append((start, end))
    return out


def _rebalance_toc_spans(
    spans: list[tuple[int, int]],
    atoms: list[TextAtom],
    *,
    hard_starts: set[int],
    max_chars: int,
    min_chars: int,
) -> list[tuple[int, int]]:
    atom_starts = sorted({atom.start for atom in atoms})
    balanced: list[tuple[int, int]] = []
    for start, end in spans:
        if (
            balanced
            and end - start < min_chars
            and start not in hard_starts
            and _span_has_toc(atoms, balanced[-1][0], end)
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
                split_at = min(
                    candidates,
                    key=lambda point: abs(point - (previous_start + end) / 2),
                )
                balanced[-1] = (previous_start, split_at)
                start = split_at
        balanced.append((start, end))
    return balanced


def _enforce_minimum_spans(
    spans: list[tuple[int, int]],
    atoms: list[TextAtom],
    *,
    text: str,
    text_length: int,
    max_chars: int,
    min_chars: int,
) -> list[tuple[int, int]]:
    """Merge heading shells to ≥200 chars and rebalance tails below the fragment floor."""
    packer_floor = _segment_floor(min_chars, max_chars)
    fragment_floor = _fragment_floor(min_chars, max_chars)
    hard_min = min(SEGMENT_HARD_MIN_CHARS, max_chars)
    if len(spans) < 2 or text_length < hard_min:
        return spans
    role_hard = _role_hard_starts(atoms)
    hard_starts = _cross_chapter_starts(atoms)
    atom_starts = [atom.start for atom in atoms]

    out = list(spans)
    i = 0
    while i < len(out):
        start, end = out[i]
        floor = packer_floor if _span_has_toc(atoms, start, end) else fragment_floor
        length = end - start
        needs_hard = length < hard_min
        needs_fragment = length < floor
        if not needs_hard and not needs_fragment:
            i += 1
            continue

        opens_chapter = _span_opens_body_chapter(atoms, start)
        neighbor: int | None = None
        if needs_hard and opens_chapter:
            nxt = i + 1
            if nxt < len(out) and not _blocks_same_chapter_merge(
                atoms, role_hard, out[nxt][0], (start, end)
            ):
                neighbor = nxt
            else:
                i += 1
                continue
        else:
            candidate = i - 1 if i > 0 else i + 1
            if candidate < 0 or candidate >= len(out):
                i += 1
                continue
            left_index, right_index = sorted((i, candidate))
            later_start = out[right_index][0]
            if _blocks_same_chapter_merge(atoms, role_hard, later_start, out[left_index]):
                other = i + 1 if candidate == i - 1 else i - 1
                if 0 <= other < len(out):
                    other_left, other_right = sorted((i, other))
                    if not _blocks_same_chapter_merge(
                        atoms, role_hard, out[other_right][0], out[other_left]
                    ):
                        neighbor = other
                if neighbor is None:
                    i += 1
                    continue
            else:
                neighbor = candidate

        left_index, right_index = sorted((i, neighbor))
        later_start = out[right_index][0]
        if later_start in hard_starts and _blocks_same_chapter_merge(
            atoms, role_hard, later_start, out[left_index]
        ):
            i += 1
            continue
        combined_start = out[left_index][0]
        combined_end = out[right_index][1]
        combined_length = combined_end - combined_start
        if combined_length <= max_chars:
            out[left_index : right_index + 1] = [(combined_start, combined_end)]
            i = max(0, left_index - 1)
            continue

        original_boundary = out[right_index][0]
        paragraph_starts = _complete_paragraph_starts(atoms)
        if (
            original_boundary in paragraph_starts
            and not _span_has_toc(atoms, combined_start, combined_end)
            and not (needs_hard and opens_chapter)
        ):
            # A whole natural paragraph that does not fit beside its neighbor
            # stays whole, even if one side is below the floor.
            i += 1
            continue

        lower = max(combined_start + floor, combined_end - max_chars)
        upper = min(combined_start + max_chars, combined_end - floor)
        if lower <= upper:
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

        # Two adjacent spans may not contain enough text for two floor-sized
        # results. Expand the local window and repartition it at natural points.
        # If floor ≈ max_chars, both cannot be satisfied; keep ceil(length/max)
        # rather than collapsing the whole document into one span.
        expanded_left = left_index
        expanded_right = right_index
        while True:
            expanded_start = out[expanded_left][0]
            expanded_end = out[expanded_right][1]
            expanded_length = expanded_end - expanded_start
            part_count = (expanded_length + max_chars - 1) // max_chars
            if part_count <= expanded_length // floor:
                break
            next_right = expanded_right + 1
            can_expand_left = (
                expanded_left > 0
                and not _blocks_same_chapter_merge(
                    atoms,
                    role_hard,
                    out[expanded_left][0],
                    out[expanded_left - 1],
                )
            )
            can_expand_right = (
                next_right < len(out)
                and not _blocks_same_chapter_merge(
                    atoms,
                    role_hard,
                    out[next_right][0],
                    (out[expanded_left][0], out[expanded_right][1]),
                )
            )
            if can_expand_left:
                expanded_left -= 1
            elif can_expand_right:
                expanded_right += 1
            else:
                break
        replacement = _balanced_partition(
            text,
            out[expanded_left][0],
            out[expanded_right][1],
            part_count=part_count,
            atoms=atoms,
            floor=floor,
            max_chars=max_chars,
            hard_starts=hard_starts,
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
    hard_starts: set[int] | None = None,
) -> list[tuple[int, int]]:
    interior = sorted(point for point in (hard_starts or ()) if start < point < end)
    if interior:
        points = [start, *interior, end]
        out: list[tuple[int, int]] = []
        for left, right in zip(points, points[1:]):
            length = right - left
            piece_count = max(1, (length + max_chars - 1) // max_chars)
            out.extend(
                _balanced_partition(
                    text,
                    left,
                    right,
                    part_count=piece_count,
                    atoms=atoms,
                    floor=floor,
                    max_chars=max_chars,
                    hard_starts=None,
                )
            )
        return out
    if part_count <= 1:
        return [(start, end)]
    atom_starts = [atom.start for atom in atoms if start < atom.start < end]
    paragraph_points = {
        point for point in _paragraph_cut_offsets(text, start, end) if start < point < end
    }
    sentence_points = {
        point for point in _sentence_cut_offsets(text, start, end) if start < point < end
    }
    atom_points = set(atom_starts)

    boundaries = [start]
    cursor = start
    for index in range(1, part_count):
        remaining_parts = part_count - index
        lower = max(cursor + floor, end - remaining_parts * max_chars)
        upper = min(cursor + max_chars, end - remaining_parts * floor)
        target = start + round((end - start) * index / part_count)
        boundary = None
        for group in (paragraph_points, sentence_points, atom_points):
            candidates = [point for point in group if lower <= point <= upper]
            if candidates:
                boundary = min(candidates, key=lambda point: abs(point - target))
                break
        if boundary is None:
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
            later = [point for point in paragraph_points if cursor < point < end]
            if not later:
                later = [point for point in sentence_points if cursor < point < end]
            if not later:
                later = [point for point in atom_points if cursor < point < end]
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
    if match_structure_line(stripped) and not is_page_line(stripped):
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
    yielder: GilYielder | None = None,
) -> list[tuple[int, int]]:
    pieces: list[tuple[int, int]] = []
    cursor = start
    while end - cursor > preferred_chars:
        if yielder is not None:
            yielder.bump(max(1, min(max_chars, end - cursor)))
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
