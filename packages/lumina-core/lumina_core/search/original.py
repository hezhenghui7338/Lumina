"""In-book original-text search (Find in page). Never returns raw_text."""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from lumina_core.db.connection import db_lock

MAX_QUERY_CHARS = 200
DEFAULT_LIMIT = 80
SNIPPET_RADIUS = 24


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
    exclusive cursor so clients can page past the default 80-hit window.
    """
    q = (query or "").strip()
    if len(q) > MAX_QUERY_CHARS:
        q = q[:MAX_QUERY_CHARS]
    if not q:
        return {"query": "", "hits": [], "truncated": False}

    pattern = re.compile(re.escape(q), re.IGNORECASE)
    hits: list[dict[str, Any]] = []
    truncated = False
    scan_limit = max(1, min(limit, 200))

    with db_lock(conn):
        rows = conn.execute(
            "SELECT idx, raw_text FROM segments WHERE book_id = ? ORDER BY idx",
            (book_id,),
        )
        for row in rows:
            seg_idx = int(row["idx"])
            if after_segment_index is not None and seg_idx < after_segment_index:
                continue
            text = row["raw_text"] or ""
            if not text:
                continue
            for match in pattern.finditer(text):
                start, end = match.span()
                if not _is_after_cursor(
                    seg_idx,
                    start,
                    after_segment_index=after_segment_index,
                    after_start=after_start,
                ):
                    continue
                hits.append(
                    {
                        "segment_index": seg_idx,
                        "start": start,
                        "end": end,
                        "start_utf16": utf16_offset(text, start),
                        "end_utf16": utf16_offset(text, end),
                        "snippet": make_snippet(text, start, end),
                    }
                )
                if len(hits) > scan_limit:
                    truncated = True
                    hits.pop()
                    break
            if truncated:
                break

    return {"query": q, "hits": hits, "truncated": truncated}
