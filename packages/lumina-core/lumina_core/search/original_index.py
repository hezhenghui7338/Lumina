"""Dedicated full-text index for in-book original search.

Separate from cross-book ``search_fts`` (which truncates raw_text to 4k and mixes
summary/translation). Updates MUST delete by FTS rowid via ``original_fts_map``.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Iterator

from lumina_core.db.connection import db_lock, db_transaction

_INDEX_BATCH = 32
_DELETE_BATCH = 100


def ensure_original_index_schema(conn: sqlite3.Connection) -> None:
    """Idempotent DDL for original_fts / map / char_seg."""
    conn.executescript(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS original_fts USING fts5(
          book_id UNINDEXED, segment_id UNINDEXED, segment_idx UNINDEXED, body,
          tokenize='trigram'
        );
        CREATE TABLE IF NOT EXISTS original_fts_map (
          segment_id TEXT PRIMARY KEY,
          book_id    TEXT NOT NULL,
          fts_rowid  INTEGER NOT NULL UNIQUE
        );
        CREATE INDEX IF NOT EXISTS idx_original_fts_map_book
          ON original_fts_map(book_id);
        CREATE TABLE IF NOT EXISTS original_char_seg (
          book_id      TEXT NOT NULL,
          ch           TEXT NOT NULL,
          segment_idx  INTEGER NOT NULL,
          PRIMARY KEY (book_id, ch, segment_idx)
        );
        CREATE INDEX IF NOT EXISTS idx_original_char_seg_lookup
          ON original_char_seg(book_id, ch, segment_idx);
        """
    )


def _lookup_rowid(conn: sqlite3.Connection, segment_id: str) -> int | None:
    row = conn.execute(
        "SELECT fts_rowid FROM original_fts_map WHERE segment_id = ?",
        (segment_id,),
    ).fetchone()
    if row is None:
        return None
    return int(row[0] if not hasattr(row, "keys") else row["fts_rowid"])


def _unique_chars(text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for ch in text:
        if ch.isspace() or ch in seen:
            continue
        seen.add(ch)
        out.append(ch)
    return out


def index_original_segment(
    conn: sqlite3.Connection,
    *,
    book_id: str,
    segment_id: str,
    segment_idx: int,
    raw_text: str,
) -> None:
    """Upsert one segment into original_fts + original_char_seg."""
    body = raw_text or ""
    with db_transaction(conn):
        rowid = _lookup_rowid(conn, segment_id)
        if rowid is not None:
            conn.execute("DELETE FROM original_fts WHERE rowid = ?", (rowid,))
            conn.execute(
                "DELETE FROM original_fts_map WHERE segment_id = ?", (segment_id,)
            )
        # Drop prior char rows for this segment_idx (reindex / move).
        conn.execute(
            "DELETE FROM original_char_seg WHERE book_id = ? AND segment_idx = ?",
            (book_id, segment_idx),
        )
        conn.execute(
            """
            INSERT INTO original_fts (book_id, segment_id, segment_idx, body)
            VALUES (?, ?, ?, ?)
            """,
            (book_id, segment_id, segment_idx, body),
        )
        new_rowid = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        conn.execute(
            """
            INSERT INTO original_fts_map (segment_id, book_id, fts_rowid)
            VALUES (?, ?, ?)
            """,
            (segment_id, book_id, new_rowid),
        )
        chars = _unique_chars(body)
        if chars:
            conn.executemany(
                """
                INSERT OR IGNORE INTO original_char_seg (book_id, ch, segment_idx)
                VALUES (?, ?, ?)
                """,
                [(book_id, ch, segment_idx) for ch in chars],
            )


def delete_book_original_index(conn: sqlite3.Connection, book_id: str) -> None:
    """Remove all original-index rows for a book (batched, yields lock)."""
    while True:
        with db_transaction(conn):
            rows = conn.execute(
                """
                SELECT segment_id, fts_rowid FROM original_fts_map
                WHERE book_id = ?
                LIMIT ?
                """,
                (book_id, _DELETE_BATCH),
            ).fetchall()
            if not rows:
                break
            for row in rows:
                seg_id = row[0] if not hasattr(row, "keys") else row["segment_id"]
                rowid = int(row[1] if not hasattr(row, "keys") else row["fts_rowid"])
                conn.execute("DELETE FROM original_fts WHERE rowid = ?", (rowid,))
                conn.execute(
                    "DELETE FROM original_fts_map WHERE segment_id = ?", (seg_id,)
                )
        time.sleep(0.001)
    with db_transaction(conn):
        conn.execute("DELETE FROM original_char_seg WHERE book_id = ?", (book_id,))


def index_book_original(
    conn: sqlite3.Connection,
    book_id: str,
    *,
    replace: bool = True,
) -> None:
    """Index every segment of a book. When ``replace``, wipe existing first."""
    if replace:
        delete_book_original_index(conn, book_id)
    next_idx = 0
    while True:
        with db_lock(conn):
            rows = conn.execute(
                """
                SELECT id, idx, raw_text FROM segments
                WHERE book_id = ? AND idx >= ?
                ORDER BY idx
                LIMIT ?
                """,
                (book_id, next_idx, _INDEX_BATCH),
            ).fetchall()
        if not rows:
            break
        for row in rows:
            seg_id = row[0] if not hasattr(row, "keys") else row["id"]
            seg_idx = int(row[1] if not hasattr(row, "keys") else row["idx"])
            text = row[2] if not hasattr(row, "keys") else row["raw_text"]
            index_original_segment(
                conn,
                book_id=book_id,
                segment_id=str(seg_id),
                segment_idx=seg_idx,
                raw_text=text or "",
            )
        next_idx = int(rows[-1][1] if not hasattr(rows[-1], "keys") else rows[-1]["idx"]) + 1
        time.sleep(0.001)


def is_original_index_ready(conn: sqlite3.Connection, book_id: str) -> bool:
    """True when mapped FTS rows cover every segment of the book."""
    with db_lock(conn):
        book = conn.execute(
            "SELECT segment_count FROM books WHERE id = ?", (book_id,)
        ).fetchone()
        if book is None:
            return False
        seg_count = int(book[0] if not hasattr(book, "keys") else book["segment_count"] or 0)
        if seg_count <= 0:
            return False
        mapped = conn.execute(
            "SELECT COUNT(*) AS c FROM original_fts_map WHERE book_id = ?",
            (book_id,),
        ).fetchone()
        map_count = int(mapped[0] if not hasattr(mapped, "keys") else mapped["c"])
    return map_count >= seg_count


def _fts_match_query(query: str) -> str:
    """Escape for FTS5 MATCH; quote so trigram treats the string as a unit."""
    cleaned = (query or "").replace('"', '""')
    return f'"{cleaned}"'


def iter_candidate_segment_indices(
    conn: sqlite3.Connection,
    book_id: str,
    query: str,
    *,
    after_segment_index: int | None = None,
) -> Iterator[int]:
    """Yield matching segment indices in ascending order (index must be ready)."""
    q = (query or "").strip()
    if not q:
        return
    min_idx = 0 if after_segment_index is None else max(0, after_segment_index)
    batch_size = 64
    if len(q) >= 3:
        match_q = _fts_match_query(q)
        cursor = min_idx
        while True:
            with db_lock(conn):
                rows = conn.execute(
                    """
                    SELECT segment_idx FROM original_fts
                    WHERE original_fts MATCH ?
                      AND book_id = ?
                      AND segment_idx >= ?
                    ORDER BY segment_idx
                    LIMIT ?
                    """,
                    (match_q, book_id, cursor, batch_size),
                ).fetchall()
            if not rows:
                return
            for row in rows:
                idx = int(row[0] if not hasattr(row, "keys") else row["segment_idx"])
                yield idx
            last = int(rows[-1][0] if not hasattr(rows[-1], "keys") else rows[-1]["segment_idx"])
            cursor = last + 1
            time.sleep(0.001)
        return

    # 1–2 char: character posting lists (intersection for length 2).
    chars = [ch for ch in q if not ch.isspace()]
    if not chars:
        return
    if len(chars) == 1:
        ch = chars[0]
        cursor = min_idx
        while True:
            with db_lock(conn):
                rows = conn.execute(
                    """
                    SELECT segment_idx FROM original_char_seg
                    WHERE book_id = ? AND ch = ? AND segment_idx >= ?
                    ORDER BY segment_idx
                    LIMIT ?
                    """,
                    (book_id, ch, cursor, batch_size),
                ).fetchall()
            if not rows:
                return
            for row in rows:
                yield int(row[0] if not hasattr(row, "keys") else row["segment_idx"])
            last = int(rows[-1][0] if not hasattr(rows[-1], "keys") else rows[-1]["segment_idx"])
            cursor = last + 1
            time.sleep(0.001)
        return

    # Length 2: intersect first two distinct chars (exact match verified later).
    a, b = chars[0], chars[1]
    cursor = min_idx
    while True:
        with db_lock(conn):
            rows = conn.execute(
                """
                SELECT a.segment_idx AS segment_idx
                FROM original_char_seg a
                INNER JOIN original_char_seg b
                  ON a.book_id = b.book_id AND a.segment_idx = b.segment_idx
                WHERE a.book_id = ?
                  AND a.ch = ?
                  AND b.ch = ?
                  AND a.segment_idx >= ?
                ORDER BY a.segment_idx
                LIMIT ?
                """,
                (book_id, a, b, cursor, batch_size),
            ).fetchall()
        if not rows:
            return
        for row in rows:
            yield int(row[0] if not hasattr(row, "keys") else row["segment_idx"])
        last = int(rows[-1][0] if not hasattr(rows[-1], "keys") else rows[-1]["segment_idx"])
        cursor = last + 1
        time.sleep(0.001)


def books_needing_original_index(conn: sqlite3.Connection) -> list[str]:
    """Book ids where segment_count > mapped original_fts rows."""
    with db_lock(conn):
        rows = conn.execute(
            """
            SELECT b.id
            FROM books b
            LEFT JOIN (
              SELECT book_id, COUNT(*) AS c FROM original_fts_map GROUP BY book_id
            ) m ON m.book_id = b.id
            WHERE COALESCE(b.segment_count, 0) > 0
              AND COALESCE(m.c, 0) < COALESCE(b.segment_count, 0)
            ORDER BY b.updated_at DESC
            """
        ).fetchall()
    return [str(r[0] if not hasattr(r, "keys") else r["id"]) for r in rows]


def backfill_original_indexes(conn: sqlite3.Connection, *, max_books: int | None = None) -> int:
    """Index books missing original coverage. Returns number of books processed."""
    ids = books_needing_original_index(conn)
    if max_books is not None:
        ids = ids[: max(0, max_books)]
    for book_id in ids:
        index_book_original(conn, book_id, replace=True)
        time.sleep(0.001)
    return len(ids)
