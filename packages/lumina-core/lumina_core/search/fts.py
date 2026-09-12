"""FTS5 indexing and cross-book search.

Updates MUST delete by FTS rowid via search_fts_map. Never
`DELETE FROM search_fts WHERE segment_id/book_id/note_id = ?` — those
columns are UNINDEXED and force a full content scan (trigram de-index).
"""

from __future__ import annotations

import re
import sqlite3
import time
from typing import Any

from lumina_core.db.connection import db_lock, db_transaction

_FTS_DELETE_BATCH = 100


def doc_key(kind: str, entity_id: str) -> str:
    return f"{kind}:{entity_id}"


def _lookup_rowid(conn: sqlite3.Connection, key: str) -> int | None:
    row = conn.execute(
        "SELECT fts_rowid FROM search_fts_map WHERE doc_key = ?", (key,)
    ).fetchone()
    if row is None:
        return None
    return int(row[0] if not hasattr(row, "keys") else row["fts_rowid"])


def _delete_by_rowid(conn: sqlite3.Connection, rowid: int) -> None:
    conn.execute("DELETE FROM search_fts WHERE rowid = ?", (rowid,))


def _upsert_map(
    conn: sqlite3.Connection,
    *,
    key: str,
    book_id: str,
    kind: str,
    fts_rowid: int,
) -> None:
    conn.execute(
        """
        INSERT INTO search_fts_map (doc_key, book_id, kind, fts_rowid)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(doc_key) DO UPDATE SET
          book_id = excluded.book_id,
          kind = excluded.kind,
          fts_rowid = excluded.fts_rowid
        """,
        (key, book_id, kind, fts_rowid),
    )


def _delete_mapped_doc(conn: sqlite3.Connection, key: str) -> None:
    rowid = _lookup_rowid(conn, key)
    if rowid is not None:
        _delete_by_rowid(conn, rowid)
    conn.execute("DELETE FROM search_fts_map WHERE doc_key = ?", (key,))


def _insert_fts_row(
    conn: sqlite3.Connection,
    *,
    book_id: str,
    segment_id: str | None,
    note_id: str | None,
    kind: str,
    title: str,
    body: str,
) -> int:
    conn.execute(
        """
        INSERT INTO search_fts (book_id, segment_id, note_id, kind, title, body)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (book_id, segment_id, note_id, kind, title, body),
    )
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def _delete_book_docs(
    conn: sqlite3.Connection,
    book_id: str,
    *,
    kinds: tuple[str, ...] | None = None,
) -> None:
    """Delete FTS docs for a book in batches, releasing the write lock between."""
    while True:
        with db_transaction(conn):
            if kinds:
                placeholders = ",".join("?" * len(kinds))
                rows = conn.execute(
                    f"""
                    SELECT doc_key, fts_rowid FROM search_fts_map
                    WHERE book_id = ? AND kind IN ({placeholders})
                    LIMIT ?
                    """,
                    (book_id, *kinds, _FTS_DELETE_BATCH),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT doc_key, fts_rowid FROM search_fts_map
                    WHERE book_id = ?
                    LIMIT ?
                    """,
                    (book_id, _FTS_DELETE_BATCH),
                ).fetchall()
            if not rows:
                return
            for row in rows:
                key = row[0] if not hasattr(row, "keys") else row["doc_key"]
                rowid = int(row[1] if not hasattr(row, "keys") else row["fts_rowid"])
                _delete_by_rowid(conn, rowid)
                conn.execute("DELETE FROM search_fts_map WHERE doc_key = ?", (key,))
        # Brief yield so list handlers can acquire db_lock between batches.
        time.sleep(0.001)


def delete_book_from_fts(conn: sqlite3.Connection, book_id: str) -> None:
    _delete_book_docs(conn, book_id, kinds=None)


def delete_book_segments_from_fts(conn: sqlite3.Connection, book_id: str) -> None:
    """Drop segment + note FTS rows for a book; keep the book title row."""
    _delete_book_docs(conn, book_id, kinds=("segment", "note"))


def index_book(conn: sqlite3.Connection, book: dict[str, Any]) -> None:
    key = doc_key("book", book["id"])
    with db_transaction(conn):
        _delete_mapped_doc(conn, key)
        rowid = _insert_fts_row(
            conn,
            book_id=book["id"],
            segment_id=None,
            note_id=None,
            kind="book",
            title=book.get("title") or "",
            body=book.get("author") or "",
        )
        _upsert_map(conn, key=key, book_id=book["id"], kind="book", fts_rowid=rowid)


def index_segment(conn: sqlite3.Connection, book: dict[str, Any], seg: dict[str, Any]) -> None:
    body_parts = [
        seg.get("label") or "",
        seg.get("summary_json") or "",
        (seg.get("raw_text") or "")[:4000],
        seg.get("translation") or "",
    ]
    key = doc_key("segment", seg["id"])
    with db_transaction(conn):
        _delete_mapped_doc(conn, key)
        rowid = _insert_fts_row(
            conn,
            book_id=seg["book_id"],
            segment_id=seg["id"],
            note_id=None,
            kind="segment",
            title=f"{book.get('title', '')} · 段 {seg['idx'] + 1}",
            body="\n".join(body_parts),
        )
        _upsert_map(
            conn,
            key=key,
            book_id=seg["book_id"],
            kind="segment",
            fts_rowid=rowid,
        )


def delete_note_from_fts(conn: sqlite3.Connection, note_id: str) -> None:
    key = doc_key("note", note_id)
    # May be called inside an existing transaction (NoteRepo.delete).
    _delete_mapped_doc(conn, key)


def index_note(conn: sqlite3.Connection, book: dict[str, Any], note: dict[str, Any]) -> None:
    key = doc_key("note", note["id"])
    with db_transaction(conn):
        _delete_mapped_doc(conn, key)
        rowid = _insert_fts_row(
            conn,
            book_id=note["book_id"],
            segment_id=note.get("segment_id"),
            note_id=note["id"],
            kind="note",
            title=f"笔记 · {book.get('title', '')}",
            body=f"{note.get('quote') or ''}\n{note.get('content') or ''}",
        )
        _upsert_map(
            conn,
            key=key,
            book_id=note["book_id"],
            kind="note",
            fts_rowid=rowid,
        )


def search(conn: sqlite3.Connection, query: str, *, limit: int = 30) -> list[dict[str, Any]]:
    q = query.strip()
    if not q:
        return []
    with db_lock(conn):
        rows = conn.execute(
            """
            SELECT book_id, segment_id, note_id, kind, title, snippet(search_fts, 4, '[', ']', '…', 10) AS snippet
            FROM search_fts
            WHERE search_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (q, limit),
        ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            if item["segment_id"]:
                seg = conn.execute(
                    "SELECT idx FROM segments WHERE id = ?", (item["segment_id"],)
                ).fetchone()
                if seg:
                    item["segment_index"] = seg["idx"]
            results.append(item)
    return results


def search_book_segments(
    conn: sqlite3.Connection,
    book_id: str,
    query: str,
    *,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """FTS over one book's segment rows. Empty/invalid query → []."""
    q = _sanitize_fts_query(query)
    if not q:
        return []
    with db_lock(conn):
        try:
            rows = conn.execute(
                """
                SELECT book_id, segment_id, kind, title,
                       snippet(search_fts, 4, '[', ']', '…', 10) AS snippet
                FROM search_fts
                WHERE search_fts MATCH ?
                  AND book_id = ?
                  AND kind = 'segment'
                ORDER BY rank
                LIMIT ?
                """,
                (q, book_id, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            if item["segment_id"]:
                seg = conn.execute(
                    "SELECT idx FROM segments WHERE id = ?", (item["segment_id"],)
                ).fetchone()
                if seg:
                    item["segment_index"] = seg["idx"]
            results.append(item)
    return results


def _sanitize_fts_query(query: str) -> str:
    cleaned = re.sub(r'["\'*^:(){}[\]]', " ", query or "")
    return " ".join(cleaned.split())
