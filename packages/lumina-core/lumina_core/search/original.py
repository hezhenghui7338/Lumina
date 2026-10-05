"""In-book original-text search (hit list). Never returns raw_text."""

from __future__ import annotations

import re
import sqlite3
import time
from typing import Any

from lumina_core.db.connection import db_lock
from lumina_core.search.original_index import (
    is_original_index_ready,
    iter_candidate_segment_indices,
)

MAX_QUERY_CHARS = 200
DEFAULT_LIMIT = 30
MAX_LIMIT = 50
SNIPPET_RADIUS = 24
# Fetch under lock, scan outside it so boundary / library can interleave on
# multi-million-char books (never-freeze).
_SCAN_BATCH = 64


def utf16_offset(text: str, index: int) -> int:
    """UTF-16 code unit index for NSRange / WinUI (Python str index → UTF-16)."""
    if index <= 0:
        return 0
    # Compute this without a codec: the pruned PyInstaller sidecar does not
    # bundle the optional UTF-16 codec, while desktop clients still need these
    # offsets. BMP code points occupy one code unit; astral code points occupy
    # a surrogate pair.
    stop = min(index, len(text))
    return sum(2 if ord(char) > 0xFFFF else 1 for char in text[:stop])


def make_snippet(text: str, start: int, end: int, *, radius: int = SNIPPET_RADIUS) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    prefix = "…" if left > 0 else ""
    suffix = "…" if right < len(text) else ""
    body = f"{text[left:start]}[{text[start:end]}]{text[end:right]}"
    compact = re.sub(r"\s+", " ", body).strip()
    return f"{prefix}{compact}{suffix}"


def _is_after_cursor(
    segment_index: int,
    start: int,
    *,
    after_segment_index: int | None,
    after_start: int | None,
) -> bool:
    """True when (segment_index, start) is strictly after the exclusive cursor."""
    if after_segment_index is None:
        return True
    if segment_index > after_segment_index:
        return True
    if segment_index < after_segment_index:
        return False
    cursor_start = 0 if after_start is None else after_start
    return start > cursor_start


def _utf16_units(char: str) -> int:
    return 2 if ord(char) > 0xFFFF else 1


def _clamp_limit(limit: int) -> int:
    return max(1, min(int(limit), MAX_LIMIT))


def _append_hits_from_text(
    hits: list[dict[str, Any]],
    *,
    seg_idx: int,
    text: str,
    label: str | None,
    pattern: re.Pattern[str],
    scan_limit: int,
    after_segment_index: int | None,
    after_start: int | None,
) -> bool:
    """Scan one segment; append hits. Returns True when truncated (limit exceeded)."""
    if not text:
        return False
    utf16_at = 0
    py_at = 0
    for match in pattern.finditer(text):
        start, end = match.span()
        if not _is_after_cursor(
            seg_idx,
            start,
            after_segment_index=after_segment_index,
            after_start=after_start,
        ):
            continue
        while py_at < start:
            utf16_at += _utf16_units(text[py_at])
            py_at += 1
        start_utf16 = utf16_at
        while py_at < end:
            utf16_at += _utf16_units(text[py_at])
            py_at += 1
        end_utf16 = utf16_at
        hit: dict[str, Any] = {
            "segment_index": seg_idx,
            "start": start,
            "end": end,
            "start_utf16": start_utf16,
            "end_utf16": end_utf16,
            "snippet": make_snippet(text, start, end),
        }
        if label:
            hit["segment_label"] = label
        hits.append(hit)
        if len(hits) > scan_limit:
            hits.pop()
            return True
    return False


def _search_linear(
    conn: sqlite3.Connection,
    book_id: str,
    q: str,
    *,
    scan_limit: int,
    after_segment_index: int | None,
    after_start: int | None,
) -> dict[str, Any]:
    """Fallback full scan when the original index is not ready."""
    pattern = re.compile(re.escape(q), re.IGNORECASE)
    hits: list[dict[str, Any]] = []
    truncated = False
    next_idx = 0 if after_segment_index is None else max(0, after_segment_index)

    while True:
        with db_lock(conn):
            rows = conn.execute(
                """
                SELECT idx, raw_text, label FROM segments
                WHERE book_id = ? AND idx >= ?
                ORDER BY idx
                LIMIT ?
                """,
                (book_id, next_idx, _SCAN_BATCH),
            ).fetchall()
        if not rows:
            break

        for row in rows:
            seg_idx = int(row["idx"])
            text = row["raw_text"] or ""
            label = (row["label"] or "").strip() or None
            if _append_hits_from_text(
                hits,
                seg_idx=seg_idx,
                text=text,
                label=label,
                pattern=pattern,
                scan_limit=scan_limit,
                after_segment_index=after_segment_index,
                after_start=after_start,
            ):
                truncated = True
                break
        if truncated:
            break
        next_idx = int(rows[-1]["idx"]) + 1
        time.sleep(0.001)

    return {
        "query": q,
        "hits": hits,
        "truncated": truncated,
        "index_ready": False,
    }


def _search_indexed(
    conn: sqlite3.Connection,
    book_id: str,
    q: str,
    *,
    scan_limit: int,
    after_segment_index: int | None,
    after_start: int | None,
) -> dict[str, Any]:
    pattern = re.compile(re.escape(q), re.IGNORECASE)
    hits: list[dict[str, Any]] = []
    truncated = False
    pending: list[int] = []

    def flush_pending() -> bool:
        nonlocal truncated
        if not pending:
            return False
        idxs = list(pending)
        pending.clear()
        placeholders = ",".join("?" * len(idxs))
        with db_lock(conn):
            rows = conn.execute(
                f"""
                SELECT idx, raw_text, label FROM segments
                WHERE book_id = ? AND idx IN ({placeholders})
                """,
                (book_id, *idxs),
            ).fetchall()
        by_idx = {
            int(row["idx"]): row
            for row in rows
        }
        for seg_idx in idxs:
            row = by_idx.get(seg_idx)
            if row is None:
                continue
            text = row["raw_text"] or ""
            label = (row["label"] or "").strip() or None
            if _append_hits_from_text(
                hits,
                seg_idx=seg_idx,
                text=text,
                label=label,
                pattern=pattern,
                scan_limit=scan_limit,
                after_segment_index=after_segment_index,
                after_start=after_start,
            ):
                truncated = True
                return True
        time.sleep(0.001)
        return False

    for seg_idx in iter_candidate_segment_indices(
        conn,
        book_id,
        q,
        after_segment_index=after_segment_index,
    ):
        pending.append(seg_idx)
        if len(pending) >= _SCAN_BATCH:
            if flush_pending():
                break
    else:
        flush_pending()

    return {
        "query": q,
        "hits": hits,
        "truncated": truncated,
        "index_ready": True,
    }


def search_original(
    conn: sqlite3.Connection,
    book_id: str,
    query: str,
    *,
    limit: int = DEFAULT_LIMIT,
    after_segment_index: int | None = None,
    after_start: int | None = None,
) -> dict[str, Any]:
    """Substring search over one book's raw_text. Empty query → no hits.

    Optional ``after_segment_index`` / ``after_start`` skip hits at or before that
    exclusive cursor so clients can page past the default hit window.

    Prefers ``original_fts`` / ``original_char_seg`` candidates; falls back to a
    linear scan when the index is incomplete (``index_ready=false``).

    Holds ``db_lock`` only while fetching batches; regex / UTF-16 work runs
    outside the lock so POST boundary and GET /books stay responsive.
    """
    q = (query or "").strip()
    if len(q) > MAX_QUERY_CHARS:
        q = q[:MAX_QUERY_CHARS]
    if not q:
        return {"query": "", "hits": [], "truncated": False, "index_ready": True}

    scan_limit = _clamp_limit(limit)
    if is_original_index_ready(conn, book_id):
        return _search_indexed(
            conn,
            book_id,
            q,
            scan_limit=scan_limit,
            after_segment_index=after_segment_index,
            after_start=after_start,
        )
    return _search_linear(
        conn,
        book_id,
        q,
        scan_limit=scan_limit,
        after_segment_index=after_segment_index,
        after_start=after_start,
    )
