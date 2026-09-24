"""Rebuild segment heading_path / chapter from EPUB TOC without resegment."""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lumina_core.chunker.markers import HASH_HEADING, clean_structure_title, lumina_chapter_label
from lumina_core.chunker.tree import (
    compress_outline_path,
    decode_heading_path,
    encode_heading_path,
    heading_path_from_chapter,
    is_part_junk_title,
    is_year_title,
    is_zeng_volume_title,
    year_core_title,
)
from lumina_core.db.connection import db_lock, db_transaction
from lumina_core.ingest.epub import list_book_toc_paths

# Re-export for tests / callers that imported from this module.
__all__ = [
    "OutlineRebuildResult",
    "OutlineRealignResult",
    "compress_outline_path",
    "compress_zeng_outline_path",
    "is_year_title",
    "is_zeng_volume_title",
    "year_core_title",
]

# 曾国藩全集 volume marker (also used for reading-order lock)
_PART_JUNK = re.compile(r"^part\d+$", re.IGNORECASE)
_VOLUME_ZENG = re.compile(r"^曾国藩全集(\d+)$")


@dataclass(frozen=True)
class OutlineRebuildResult:
    book_id: str
    segment_count: int
    updated: int
    unchanged: int
    unmatched: int
    toc_entries: int
    mode: str  # toc | heuristic | mixed


@dataclass(frozen=True)
class OutlineRealignResult:
    book_id: str
    splits: int
    outline: OutlineRebuildResult
    resummarize_indices: list[int]


def is_part_junk(title: str) -> bool:
    return is_part_junk_title(title)


def compress_zeng_outline_path(path: list[str] | tuple[str, ...]) -> list[str]:
    """Backward-compatible wrapper: path only (label discarded)."""
    compressed, _label = compress_outline_path(path)
    return compressed


def normalize_outline_title(title: str) -> str:
    """Fuzzy key for TOC leaf matching (fullwidth dots, spaces, footnote marks)."""
    text = clean_structure_title(title)
    text = text.replace("．", ".").replace("　", " ")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"\[\d+\]", "", text)
    text = re.sub(r"\(\d+\)$", "", text)
    return text


def titles_from_raw_tip(raw: str | None, *, limit: int = 1000) -> list[str]:
    """Structure titles from leading Lumina markers in a raw_text tip."""
    return [title for _level, title in marker_entries_from_tip(raw, limit=limit)]


def marker_entries_from_tip(
    raw: str | None, *, limit: int = 1000
) -> list[tuple[int, str]]:
    """Leading hash markers as (hash_count, cleaned_title); skips EPUB partNNNN junk."""
    if not raw:
        return []
    tip = raw[:limit]
    entries: list[tuple[int, str]] = []
    for line in tip.splitlines():
        stripped = line.strip()
        if not stripped:
            if entries:
                break
            continue
        match = HASH_HEADING.match(stripped)
        if match is None:
            if entries:
                break
            continue
        cleaned = clean_structure_title(match.group(2))
        if not cleaned or is_part_junk(cleaned):
            continue
        entries.append((len(match.group(1)), cleaned))
    return entries


def segment_path_hints(
    *,
    heading_path: list[str] | None,
    chapter: str | None,
    raw_tip: str | None = None,
) -> list[str]:
    """Candidate titles for TOC matching (markers > heading_path > chapter)."""
    from_markers = titles_from_raw_tip(raw_tip)
    if from_markers:
        return from_markers
    stored = [
        clean_structure_title(t)
        for t in (heading_path or [])
        if clean_structure_title(t) and not is_part_junk(t)
    ]
    if stored:
        return stored
    return [
        t
        for t in heading_path_from_chapter(chapter)
        if t and not is_part_junk(t)
    ]


def volume_roots_from_toc(toc_paths: list[tuple[str, ...]]) -> set[str]:
    """Top-level collection titles (e.g. 曾国藩全集1…31)."""
    singles = {path[0] for path in toc_paths if len(path) == 1}
    if singles:
        return singles
    return {path[0] for path in toc_paths if path}


def is_volume_title(title: str, volume_roots: set[str] | None = None) -> bool:
    name = clean_structure_title(title)
    if not name:
        return False
    if volume_roots and name in volume_roots:
        return True
    return bool(_VOLUME_ZENG.match(name))


def sanitize_outline_path(
    path: list[str] | tuple[str, ...],
    *,
    volume_roots: set[str] | None = None,
) -> list[str]:
    """Drop part junk and collapse accidental multi-volume nests (no depth cap)."""
    cleaned = [
        clean_structure_title(title)
        for title in path
        if clean_structure_title(title) and not is_part_junk(title)
    ]
    vol_idxs = [
        index
        for index, title in enumerate(cleaned)
        if is_volume_title(title, volume_roots)
    ]
    if len(vol_idxs) > 1:
        cleaned = cleaned[vol_idxs[-1] :]
    return cleaned


def sanitize_outline_path_with_label(
    path: list[str] | tuple[str, ...],
    *,
    volume_roots: set[str] | None = None,
) -> tuple[list[str], str | None]:
    """Volume-sanitize then cap at two title levels; tertiary → label."""
    return compress_outline_path(
        sanitize_outline_path(path, volume_roots=volume_roots)
    )


def parse_volume_number(title: str) -> int | None:
    name = clean_structure_title(title)
    match = _VOLUME_ZENG.match(name)
    if match:
        return int(match.group(1))
    return None


def detect_volume_h1_markers(
    raw_tips: list[str],
    *,
    segment_indices: list[int] | None = None,
) -> list[tuple[int, int]]:
    """Return (segment_idx, volume_number) for leading ``# [§曾国藩全集N]`` markers."""
    indices = segment_indices or list(range(len(raw_tips)))
    found: list[tuple[int, int]] = []
    for tip, seg_idx in zip(raw_tips, indices):
        for level, title in marker_entries_from_tip(tip, limit=400):
            if level != 1:
                continue
            number = parse_volume_number(title)
            if number is None:
                continue
            found.append((int(seg_idx), number))
            break
    return found


# Full-line Lumina volume marker: ``# [§曾国藩全集13]``
_VOLUME_MARKER_LINE = re.compile(
    r"(?m)^(#{1,6}) \[§(曾国藩全集\d+)\][ \t]*$"
)


@dataclass(frozen=True)
class VolumeMarkerHit:
    segment_index: int
    offset: int
    volume: int
    at_start: bool


def find_volume_markers_full_text(
    segments: list[tuple[int, str]],
) -> list[VolumeMarkerHit]:
    """Scan full ``raw_text`` for ``# [§曾国藩全集N]`` (not tip-only)."""
    hits: list[VolumeMarkerHit] = []
    for seg_idx, raw in segments:
        text = raw or ""
        for match in _VOLUME_MARKER_LINE.finditer(text):
            number = parse_volume_number(match.group(2))
            if number is None:
                continue
            offset = match.start()
            at_start = text[:offset].strip() == ""
            hits.append(
                VolumeMarkerHit(
                    segment_index=int(seg_idx),
                    offset=offset,
                    volume=number,
                    at_start=at_start,
                )
            )
    return hits


def build_volume_ranges_strict(
    markers: list[tuple[int, int]],
    *,
    segment_count: int,
) -> list[tuple[int, int, int]]:
    """Half-open ranges from marker positions only — no TOC weight interpolation.

    Segments before the first marker belong to that first volume. Each subsequent
    ``# [§曾国藩全集N]`` at segment start owns until the next marker.
    """
    if segment_count <= 0 or not markers:
        return []
    ordered = sorted(markers, key=lambda item: item[0])
    # First occurrence of each volume in reading order.
    points: list[tuple[int, int]] = []
    seen: set[int] = set()
    for seg_idx, vol in ordered:
        if vol in seen or vol < 1:
            continue
        points.append((max(0, min(int(seg_idx), segment_count)), vol))
        seen.add(vol)
    if not points:
        return []
    # Material before the first marker still counts as that volume.
    first_idx, first_vol = points[0]
    if first_idx > 0:
        points[0] = (0, first_vol)
    points.append((segment_count, points[-1][1] + 1))

    ranges: list[tuple[int, int, int]] = []
    for (start, vol), (end, _next_vol) in zip(points, points[1:]):
        if start < end:
            ranges.append((start, end, vol))
    return ranges


def toc_volume_weights(toc_paths: list[tuple[str, ...]]) -> dict[int, int]:
    weights: dict[int, int] = {}
    for path in toc_paths:
        if not path:
            continue
        number = parse_volume_number(path[0])
        if number is None:
            continue
        weights[number] = weights.get(number, 0) + 1
    return weights


def build_volume_ranges_from_markers(
    markers: list[tuple[int, int]],
    *,
    segment_count: int,
    toc_weights: dict[int, int] | None = None,
    max_volume: int | None = None,
) -> list[tuple[int, int, int]]:
    """Map half-open [start, end) segment idx ranges → volume number 1..N in order.

    Known ``# [§曾国藩全集N]`` markers are hard boundaries. Missing volumes between
    two markers are split by EPUB TOC entry weight so 1–31 stay in reading order.
    """
    if segment_count <= 0:
        return []
    weights = toc_weights or {}
    highest = max_volume
    if highest is None:
        highest = max(
            [vol for _idx, vol in markers] + list(weights.keys()) + [0]
        )
    if highest <= 0:
        return [(0, segment_count, 1)]

    # Start volume 1 at idx 0; keep first marker per volume number.
    points: list[tuple[int, int]] = [(0, 1)]
    seen = {1}
    for seg_idx, vol in sorted(markers, key=lambda item: item[0]):
        if vol in seen:
            continue
        if vol < 1:
            continue
        points.append((max(0, min(seg_idx, segment_count)), vol))
        seen.add(vol)
    points.append((segment_count, highest + 1))

    ranges: list[tuple[int, int, int]] = []
    for (start, vol_start), (end, vol_end) in zip(points, points[1:]):
        volumes = list(range(vol_start, vol_end))
        if not volumes:
            continue
        if start >= end:
            continue
        if len(volumes) == 1:
            ranges.append((start, end, volumes[0]))
            continue
        span = end - start
        raw_weights = [max(1, int(weights.get(vol, 1))) for vol in volumes]
        total_w = sum(raw_weights)
        cursor = start
        for offset, vol in enumerate(volumes):
            remaining = len(volumes) - offset
            if remaining == 1:
                next_end = end
            else:
                share = max(1, int(round(span * raw_weights[offset] / total_w)))
                next_end = min(cursor + share, end - (remaining - 1))
            ranges.append((cursor, next_end, vol))
            cursor = next_end
    return ranges


def volume_title_for_number(number: int, volume_roots: set[str] | None = None) -> str:
    candidate = f"曾国藩全集{number}"
    if volume_roots:
        for root in volume_roots:
            if parse_volume_number(root) == number:
                return root
    return candidate


def apply_volume_reading_order(
    paths: list[list[str]],
    *,
    segment_indices: list[int],
    ranges: list[tuple[int, int, int]],
    toc_paths: list[tuple[str, ...]] | None = None,
    volume_roots: set[str] | None = None,
) -> list[list[str]]:
    """Force path[0] to the volume implied by reading-order ranges (1→31)."""
    if not ranges:
        return paths

    def volume_at(seg_idx: int) -> int:
        for start, end, vol in ranges:
            if start <= seg_idx < end:
                return vol
        return ranges[-1][2]

    # TOC paths keyed by volume title for suffix rematch.
    by_vol: dict[str, list[tuple[str, ...]]] = {}
    for path in toc_paths or []:
        if not path:
            continue
        by_vol.setdefault(path[0], []).append(path)

    out: list[list[str]] = []
    for path, seg_idx in zip(paths, segment_indices):
        vol_num = volume_at(int(seg_idx))
        vol_title = volume_title_for_number(vol_num, volume_roots)
        rest = [
            title
            for title in path
            if clean_structure_title(title)
            and not is_part_junk(title)
            and not is_volume_title(title, volume_roots)
        ]
        rematched: list[str] | None = None
        vol_toc = by_vol.get(vol_title) or []
        if rest and vol_toc:
            for leaf in reversed(rest):
                key = normalize_outline_title(leaf)
                for candidate in vol_toc:
                    if normalize_outline_title(candidate[-1]) == key:
                        rematched = list(candidate)
                        break
                if rematched is not None:
                    break
        if rematched is not None:
            out.append(sanitize_outline_path(rematched, volume_roots=volume_roots))
            continue
        if rest:
            # Keep year crumbs under the corrected volume (articles dropped later
            # by compress_zeng_outline_path for 曾国藩全集N roots).
            year = next((title for title in rest if is_year_title(title)), None)
            rebuilt = [vol_title]
            if year:
                rebuilt.append(year)
            elif rest:
                rebuilt.append(rest[0])
            out.append(sanitize_outline_path(rebuilt, volume_roots=volume_roots))
        else:
            out.append([vol_title])
    return out


def assign_paths_from_toc(
    segment_hints: list[list[str]],
    toc_paths: list[tuple[str, ...]],
) -> list[tuple[str, ...] | None]:
    """Map each segment's title hints to a TOC full path (sequential, sticky leaf).

    Uses normalized leaf keys so 「001．折」 matches 「001. 折」, and prefers
    matches inside the current volume when several TOC leaves share a title.
    """
    if not toc_paths:
        return [None] * len(segment_hints)

    volume_roots = volume_roots_from_toc(toc_paths)
    by_leaf: dict[str, list[int]] = defaultdict(list)
    for index, path in enumerate(toc_paths):
        if not path:
            continue
        by_leaf[normalize_outline_title(path[-1])].append(index)
        # Exact key too (tests / simple titles).
        by_leaf.setdefault(path[-1], []).append(index)

    out: list[tuple[str, ...] | None] = []
    cursor = 0
    last_matched: tuple[str, ...] | None = None
    sticky_volume: str | None = None

    for hints in segment_hints:
        cleaned_hints = [
            clean_structure_title(title)
            for title in hints
            if clean_structure_title(title) and not is_part_junk(title)
        ]
        for title in cleaned_hints:
            if is_volume_title(title, volume_roots):
                # Only jump when entering a *different* volume. Body segments often
                # restate the current 全集N via heading_path fallback; resetting the
                # cursor to the volume start would make later month-only leaves
                # (十二月/二月) snap back to the first year (e.g. 道光十九年).
                if title != sticky_volume:
                    sticky_volume = title
                    for index, path in enumerate(toc_paths):
                        if path and path[0] == title:
                            cursor = index
                            break
                else:
                    sticky_volume = title

        matched: tuple[str, ...] | None = None
        leaf_candidates = list(reversed(cleaned_hints)) if cleaned_hints else []
        for leaf in leaf_candidates:
            if last_matched and (
                last_matched[-1] == leaf
                or normalize_outline_title(last_matched[-1])
                == normalize_outline_title(leaf)
            ):
                matched = last_matched
                break
            indices = by_leaf.get(normalize_outline_title(leaf)) or by_leaf.get(leaf) or []
            ordered: list[int] = []
            seen: set[int] = set()
            for index in indices:
                if index in seen:
                    continue
                seen.add(index)
                ordered.append(index)
            # Never fall back to TOC indices before cursor — that rewinds years
            # when a month title repeats under every diary year.
            forward = [i for i in ordered if i >= cursor]
            if not forward:
                continue
            pool = forward
            if sticky_volume:
                same_vol = [
                    i
                    for i in pool
                    if toc_paths[i] and toc_paths[i][0] == sticky_volume
                ]
                if same_vol:
                    pool = same_vol
            if not pool:
                continue
            chosen = pool[0]
            matched = toc_paths[chosen]
            cursor = chosen
            break

        if matched is None and cleaned_hints:
            hint_tuple = tuple(cleaned_hints)
            hint_norm = tuple(normalize_outline_title(t) for t in cleaned_hints)
            for index in range(cursor, len(toc_paths)):
                path = toc_paths[index]
                if not path:
                    continue
                if path == hint_tuple:
                    matched = path
                    cursor = index
                    break
                path_norm = tuple(normalize_outline_title(t) for t in path)
                if len(hint_norm) <= len(path_norm) and path_norm[-len(hint_norm) :] == hint_norm:
                    matched = path
                    cursor = index
                    break

        if matched is not None:
            matched = tuple(
                sanitize_outline_path(matched, volume_roots=volume_roots)
            ) or matched
            last_matched = matched
            sticky_volume = matched[0]
        out.append(matched)
    return out


def fill_sticky_outline_paths(
    assigned: list[tuple[str, ...] | None],
    segment_hints: list[list[str]],
    *,
    volume_roots: set[str] | None = None,
) -> list[list[str]]:
    """Inherit the last TOC path for body segments; honor volume/year marker bumps."""
    final: list[list[str]] = []
    sticky: list[str] | None = None
    sticky_volume: str | None = None

    for matched, hints in zip(assigned, segment_hints):
        cleaned_hints = [
            clean_structure_title(title)
            for title in hints
            if clean_structure_title(title) and not is_part_junk(title)
        ]
        for title in cleaned_hints:
            if is_volume_title(title, volume_roots):
                sticky_volume = title

        if matched:
            sticky = sanitize_outline_path(matched, volume_roots=volume_roots)
            if sticky:
                sticky_volume = sticky[0]
            final.append(list(sticky))
            continue

        path: list[str] = []
        if sticky_volume and any(is_volume_title(t, volume_roots) for t in cleaned_hints):
            path = [sticky_volume]
            for title in cleaned_hints:
                if is_year_title(title):
                    path = [sticky_volume, title]
                    break
        elif sticky:
            path = list(sticky)
            for title in cleaned_hints:
                if is_year_title(title) and sticky_volume:
                    path = [sticky_volume, title]
                    break
                if is_volume_title(title, volume_roots):
                    path = [title]
                    sticky_volume = title
                    break
        elif sticky_volume:
            path = [sticky_volume]
            for title in cleaned_hints:
                if is_year_title(title):
                    path = [sticky_volume, title]
                    break

        path = sanitize_outline_path(path, volume_roots=volume_roots)
        if path:
            sticky = path
        final.append(path)

    return final


def nest_year_paths_heuristic(paths: list[list[str]]) -> list[list[str]]:
    """Nest year/article under the last collection when TOC flat or unmatched.

    Typical broken EPUB shape: [合集], [年份], [文章] as siblings →
    [合集], [合集, 年份], [合集, 年份, 文章].
    """
    collection: str | None = None
    year: str | None = None
    repaired: list[list[str]] = []
    for original in paths:
        titles = [
            clean_structure_title(t)
            for t in original
            if clean_structure_title(t) and not is_part_junk(t)
        ]
        if not titles:
            repaired.append([])
            continue
        if len(titles) == 1:
            title = titles[0]
            if is_year_title(title):
                year = title
                repaired.append([collection, year] if collection else [year])
            elif collection and year:
                repaired.append([collection, year, title])
            else:
                collection = title
                year = None
                repaired.append([collection])
            continue
        if len(titles) >= 2 and is_year_title(titles[0]):
            year = titles[0]
            if collection:
                repaired.append([collection, *titles])
            else:
                repaired.append(titles)
            continue
        if len(titles) >= 2 and is_year_title(titles[1]):
            collection = titles[0]
            year = titles[1]
            repaired.append(titles)
            continue
        if collection and year and titles[0] not in {collection, year}:
            repaired.append([collection, year, *titles])
            continue
        if not is_year_title(titles[0]):
            collection = titles[0]
            if len(titles) > 1 and is_year_title(titles[1]):
                year = titles[1]
        repaired.append(titles)
    return repaired


def rebuild_outline_for_book(
    conn: sqlite3.Connection,
    book_id: str,
    *,
    epub_path: Path | str | None = None,
    use_heuristic: bool = True,
) -> OutlineRebuildResult:
    """Update heading_path + chapter only. Does not touch raw_text or summaries."""
    lock = db_lock(conn)
    with lock:
        book = conn.execute(
            "SELECT id, title, format, file_path FROM books WHERE id = ?",
            (book_id,),
        ).fetchone()
        if book is None:
            raise ValueError(f"book not found: {book_id}")
        rows = conn.execute(
            """
            SELECT id, idx, chapter, heading_path, label,
                   substr(raw_text, 1, 1000) AS raw_tip
            FROM segments
            WHERE book_id = ?
            ORDER BY idx
            """,
            (book_id,),
        ).fetchall()

    source = Path(str(epub_path or book["file_path"] or ""))
    toc_paths: list[tuple[str, ...]] = []
    fmt = str(book["format"] or "").lower()
    if source.is_file():
        toc_paths = list_book_toc_paths(source, format_name=fmt)

    volume_roots = volume_roots_from_toc(toc_paths) if toc_paths else set()
    hints: list[list[str]] = []
    current_paths: list[list[str]] = []
    for row in rows:
        path = decode_heading_path(row["heading_path"], chapter=row["chapter"])
        current_paths.append(path)
        hints.append(
            segment_path_hints(
                heading_path=path,
                chapter=row["chapter"],
                raw_tip=row["raw_tip"],
            )
        )

    assigned = assign_paths_from_toc(hints, toc_paths) if toc_paths else [None] * len(rows)
    matched_count = sum(1 for item in assigned if item)
    mode = "toc" if toc_paths and matched_count else "heuristic"

    if toc_paths:
        final_paths = fill_sticky_outline_paths(
            assigned, hints, volume_roots=volume_roots
        )
    else:
        final_paths = [list(path) for path in current_paths]

    # Heuristic only when TOC barely matched (old flat-sibling books).
    if use_heuristic and (
        not toc_paths
        or matched_count < max(1, len(rows) // 10)
        or any(len(p) == 1 and is_year_title(p[0]) for p in final_paths if p)
    ):
        final_paths = nest_year_paths_heuristic(final_paths)
        mode = "mixed" if toc_paths else "heuristic"

    final_paths = [
        sanitize_outline_path(path, volume_roots=volume_roots) for path in final_paths
    ]

    # Reading-order volume lock: only markers at segment start count.
    # Mid-segment markers must be split first via realign_volume_markers_for_book.
    segment_indices = [int(row["idx"]) for row in rows]
    start_markers: list[tuple[int, int]] = []
    for row in rows:
        tip = str(row["raw_tip"] or "")
        hits = find_volume_markers_full_text([(int(row["idx"]), tip)])
        for hit in hits:
            if hit.at_start:
                start_markers.append((hit.segment_index, hit.volume))
                break
    if start_markers:
        vol_ranges = build_volume_ranges_strict(
            start_markers,
            segment_count=(max(segment_indices) + 1) if segment_indices else len(rows),
        )
        if vol_ranges:
            final_paths = apply_volume_reading_order(
                final_paths,
                segment_indices=segment_indices,
                ranges=vol_ranges,
                toc_paths=toc_paths,
                volume_roots=volume_roots,
            )
            mode = "toc" if toc_paths else mode

    updated = 0
    unchanged = 0
    unmatched = 0
    with db_transaction(conn):
        for row, old_path, new_path in zip(rows, current_paths, final_paths):
            cleaned, tertiary = sanitize_outline_path_with_label(
                new_path, volume_roots=volume_roots
            )
            if not cleaned:
                unmatched += 1
                continue
            stored_raw = [
                clean_structure_title(title)
                for title in old_path
                if clean_structure_title(title)
            ]
            existing_label = clean_structure_title(str(row["label"] or ""))
            label_needs = bool(tertiary) and tertiary != existing_label
            if cleaned == stored_raw and not label_needs:
                unchanged += 1
                continue
            chapter = lumina_chapter_label(" · ".join(cleaned))
            if tertiary:
                conn.execute(
                    """
                    UPDATE segments
                    SET chapter = ?, heading_path = ?, label = ?
                    WHERE id = ?
                    """,
                    (chapter, encode_heading_path(cleaned), tertiary, row["id"]),
                )
            else:
                conn.execute(
                    """
                    UPDATE segments
                    SET chapter = ?, heading_path = ?
                    WHERE id = ?
                    """,
                    (chapter, encode_heading_path(cleaned), row["id"]),
                )
            updated += 1
        conn.execute(
            "UPDATE books SET updated_at = datetime('now') WHERE id = ?",
            (book_id,),
        )

    return OutlineRebuildResult(
        book_id=book_id,
        segment_count=len(rows),
        updated=updated,
        unchanged=unchanged,
        unmatched=unmatched,
        toc_entries=len(toc_paths),
        mode=mode,
    )


def realign_volume_markers_for_book(
    conn: sqlite3.Connection,
    book_id: str,
    *,
    epub_path: Path | str | None = None,
) -> OutlineRealignResult:
    """Split mid-segment ``# [§曾国藩全集N]`` markers onto new segment starts,
    then rebuild outline paths strictly from those positions.

    Returns segment indices whose text changed (both sides of each split) so the
    caller can re-queue summaries. Does not enqueue jobs itself.
    """
    from lumina_core.db.repos import BookRepo, SegmentRepo
    from lumina_core.search.fts import index_segment

    lock = db_lock(conn)
    with lock:
        book = conn.execute(
            "SELECT id, title, format, file_path FROM books WHERE id = ?",
            (book_id,),
        ).fetchone()
        if book is None:
            raise ValueError(f"book not found: {book_id}")
        rows = conn.execute(
            """
            SELECT idx, raw_text FROM segments
            WHERE book_id = ?
            ORDER BY idx
            """,
            (book_id,),
        ).fetchall()

    segments = [(int(row["idx"]), str(row["raw_text"] or "")) for row in rows]
    hits = find_volume_markers_full_text(segments)
    # One split per volume: first mid-segment occurrence in reading order.
    to_split: dict[int, VolumeMarkerHit] = {}
    for hit in hits:
        if hit.at_start:
            continue
        if hit.volume in to_split:
            continue
        to_split[hit.volume] = hit

    # High idx first so earlier indices stay stable while shifting.
    split_plan = sorted(
        to_split.values(), key=lambda hit: hit.segment_index, reverse=True
    )
    repo = SegmentRepo(conn)
    book_dict = dict(book)
    affected: set[int] = set()
    splits = 0

    for hit in split_plan:
        # Bump previously recorded idxs that sit after this split point.
        affected = {(i + 1 if i > hit.segment_index else i) for i in affected}
        left, right = repo.split_segment_at(
            book_id, hit.segment_index, hit.offset
        )
        splits += 1
        affected.add(int(left["idx"]))
        affected.add(int(right["idx"]))
        index_segment(conn, book_dict, left)
        index_segment(conn, book_dict, right)

    outline = rebuild_outline_for_book(
        conn, book_id, epub_path=epub_path, use_heuristic=False
    )

    resummarize = sorted(affected)
    # Split already set both sides to pending; book is no longer fully summarized.
    if resummarize:
        BookRepo(conn).update(book_id, status="reading", summarize_intent="active")

    return OutlineRealignResult(
        book_id=book_id,
        splits=splits,
        outline=outline,
        resummarize_indices=resummarize,
    )


def find_books_by_title(
    conn: sqlite3.Connection,
    *,
    title_contains: str,
) -> list[dict[str, Any]]:
    needle = f"%{title_contains}%"
    with db_lock(conn):
        rows = conn.execute(
            """
            SELECT id, title, format, file_path, segment_count
            FROM books
            WHERE title LIKE ?
            ORDER BY updated_at DESC
            """,
            (needle,),
        ).fetchall()
    return [dict(row) for row in rows]
