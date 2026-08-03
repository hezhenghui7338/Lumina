"""FTS5 indexing and cross-book search."""

from __future__ import annotations

import sqlite3
from typing import Any

from lumina_core.db.connection import db_lock, db_transaction


def delete_book_from_fts(conn: sqlite3.Connection, book_id: str) -> None:
    with db_transaction(conn):
        conn.execute("DELETE FROM search_fts WHERE book_id = ?", (book_id,))


def index_book(conn: sqlite3.Connection, book: dict[str, Any]) -> None:
    with db_transaction(conn):
        conn.execute("DELETE FROM search_fts WHERE book_id = ? AND kind = 'book'", (book["id"],))
        conn.execute(
            """
            INSERT INTO search_fts (book_id, segment_id, note_id, kind, title, body)
            VALUES (?, NULL, NULL, 'book', ?, ?)
            """,
            (book["id"], book.get("title") or "", book.get("author") or ""),
        )


def index_segment(conn: sqlite3.Connection, book: dict[str, Any], seg: dict[str, Any]) -> None:
    body_parts = [
        seg.get("label") or "",
        seg.get("summary_json") or "",
        (seg.get("raw_text") or "")[:4000],
        seg.get("translation") or "",
    ]
    with db_transaction(conn):
        conn.execute("DELETE FROM search_fts WHERE segment_id = ?", (seg["id"],))
        conn.execute(
            """
            INSERT INTO search_fts (book_id, segment_id, note_id, kind, title, body)
            VALUES (?, ?, NULL, 'segment', ?, ?)
            """,
            (
                seg["book_id"],
                seg["id"],
                f"{book.get('title', '')} · 段 {seg['idx'] + 1}",
                "\n".join(body_parts),
            ),
        )


def delete_note_from_fts(conn: sqlite3.Connection, note_id: str) -> None:
    conn.execute("DELETE FROM search_fts WHERE note_id = ?", (note_id,))


def index_note(conn: sqlite3.Connection, book: dict[str, Any], note: dict[str, Any]) -> None:
    with db_transaction(conn):
        delete_note_from_fts(conn, note["id"])
        conn.execute(
            """
            INSERT INTO search_fts (book_id, segment_id, note_id, kind, title, body)
            VALUES (?, ?, ?, 'note', ?, ?)
            """,
            (
                note["book_id"],
                note.get("segment_id"),
                note["id"],
                f"笔记 · {book.get('title', '')}",
                f"{note.get('quote') or ''}\n{note.get('content') or ''}",
            ),
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
