"""Data access layer."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from lumina_core.db.connection import db_transaction
from lumina_core.search.fts import delete_note_from_fts


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


BOOK_COLLECTIONS = frozenset({"all", "unread", "reading", "summarized"})
BOOK_SORTS = frozenset({"recent", "added", "title", "favorite"})

_COLLECTION_WHERE: dict[str, str] = {
    "all": "",
    "unread": "status = 'unread'",
    "reading": "status = 'reading'",
    "summarized": "status = 'summarized'",
}

_SORT_ORDER: dict[str, str] = {
    "recent": "last_opened_at IS NULL, last_opened_at DESC, updated_at DESC",
    "added": "created_at DESC",
    "title": "title COLLATE NOCASE ASC",
    "favorite": "is_favorite DESC, last_opened_at IS NULL, last_opened_at DESC, updated_at DESC",
}


class BookRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def find_by_hash(self, file_hash: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM books WHERE file_hash = ?", (file_hash,)
        ).fetchone()
        return dict(row) if row else None

    def get(self, book_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        return dict(row) if row else None

    def list_books(
        self,
        *,
        collection: str = "all",
        sort: str = "recent",
    ) -> list[dict[str, Any]]:
        if collection not in BOOK_COLLECTIONS:
            collection = "all"
        if sort not in BOOK_SORTS:
            sort = "recent"
        where = _COLLECTION_WHERE[collection]
        order = _SORT_ORDER[sort]
        sql = "SELECT * FROM books"
        if where:
            sql += f" WHERE {where}"
        sql += f" ORDER BY {order}"
        rows = self.conn.execute(sql).fetchall()
        return [dict(r) for r in rows]

    def insert(self, **fields: Any) -> dict[str, Any]:
        book_id = fields.get("id") or str(uuid.uuid4())
        now = _now()
        with db_transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO books (
                  id, title, author, format, file_path, language, target_language,
                  segment_count, status, file_hash, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    book_id,
                    fields["title"],
                    fields.get("author"),
                    fields["format"],
                    fields["file_path"],
                    fields.get("language"),
                    fields.get("target_language"),
                    fields.get("segment_count", 0),
                    fields.get("status", "unread"),
                    fields.get("file_hash"),
                    json.dumps(fields.get("metadata_json") or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return self.get(book_id)  # type: ignore[return-value]

    def update(self, book_id: str, **fields: Any) -> None:
        fields["updated_at"] = _now()
        if "metadata_json" in fields and isinstance(fields["metadata_json"], dict):
            fields["metadata_json"] = json.dumps(fields["metadata_json"], ensure_ascii=False)
        cols = ", ".join(f"{k} = ?" for k in fields)
        with db_transaction(self.conn):
            self.conn.execute(
                f"UPDATE books SET {cols} WHERE id = ?",
                (*fields.values(), book_id),
            )

    def delete(self, book_id: str) -> None:
        with db_transaction(self.conn):
            self.conn.execute("DELETE FROM notes WHERE book_id = ?", (book_id,))
            self.conn.execute(
                """
                DELETE FROM chat_messages
                WHERE session_id IN (
                    SELECT id FROM chat_sessions WHERE book_id = ?
                )
                """,
                (book_id,),
            )
            self.conn.execute("DELETE FROM chat_sessions WHERE book_id = ?", (book_id,))
            self.conn.execute("DELETE FROM segments WHERE book_id = ?", (book_id,))
            self.conn.execute("DELETE FROM jobs WHERE book_id = ?", (book_id,))
            self.conn.execute("DELETE FROM search_fts WHERE book_id = ?", (book_id,))
            self.conn.execute("DELETE FROM books WHERE id = ?", (book_id,))

    def maybe_mark_summarized(self, book_id: str) -> bool:
        """If every segment is ready, promote book status to summarized."""
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN summary_status = 'ready' THEN 1 ELSE 0 END) AS ready
            FROM segments WHERE book_id = ?
            """,
            (book_id,),
        ).fetchone()
        if not row or row["total"] == 0 or row["ready"] != row["total"]:
            return False
        self.update(book_id, status="summarized")
        return True

    def summary_progress(self, book_id: str) -> dict[str, int]:
        """Return ready/total segment counts for summary progress UI."""
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN summary_status = 'ready' THEN 1 ELSE 0 END) AS ready
            FROM segments WHERE book_id = ?
            """,
            (book_id,),
        ).fetchone()
        if not row:
            return {"summary_ready_count": 0, "summary_total_count": 0}
        return {
            "summary_ready_count": int(row["ready"] or 0),
            "summary_total_count": int(row["total"] or 0),
        }


# List API / UI sidebar: exclude raw_text, translation, and summary_json.
_SEGMENT_META_COLUMNS = (
    "id, book_id, idx, chapter, page_range, anchor_label, char_count, "
    "label, summary_status, retry_count, "
    "summary_provider, summary_model, summary_duration_s, summary_llm_attempts"
)

_SEGMENT_SUMMARY_COLUMNS = (
    "idx, summary_json, label, anchor_label, summary_status, "
    "summary_provider, summary_model, summary_duration_s, summary_llm_attempts"
)

# Export: summary + translation without loading raw_text.
_SEGMENT_EXPORT_COLUMNS = (
    "id, book_id, idx, chapter, page_range, anchor_label, char_count, "
    "summary_json, label, summary_status, retry_count, "
    "summary_provider, summary_model, summary_duration_s, summary_llm_attempts, translation"
)


class SegmentRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def list_for_book(
        self, book_id: str, *, include_body: bool = True
    ) -> list[dict[str, Any]]:
        if not include_body:
            self._backfill_char_counts(book_id)
        cols = "*" if include_body else _SEGMENT_META_COLUMNS
        rows = self.conn.execute(
            f"SELECT {cols} FROM segments WHERE book_id = ? ORDER BY idx",
            (book_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_for_export(self, book_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            f"SELECT {_SEGMENT_EXPORT_COLUMNS} FROM segments WHERE book_id = ? ORDER BY idx",
            (book_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _backfill_char_counts(self, book_id: str) -> None:
        row = self.conn.execute(
            """
            SELECT 1 FROM segments
            WHERE book_id = ?
              AND raw_text IS NOT NULL
              AND (char_count IS NULL OR char_count = 0)
            LIMIT 1
            """,
            (book_id,),
        ).fetchone()
        if not row:
            return
        with db_transaction(self.conn):
            self.conn.execute(
                """
                UPDATE segments
                SET char_count = LENGTH(raw_text)
                WHERE book_id = ?
                  AND raw_text IS NOT NULL
                  AND (char_count IS NULL OR char_count = 0)
                """,
                (book_id,),
            )

    def get(self, segment_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM segments WHERE id = ?", (segment_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_by_index(self, book_id: str, idx: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM segments WHERE book_id = ? AND idx = ?",
            (book_id, idx),
        ).fetchone()
        return dict(row) if row else None

    def get_summary_by_index(self, book_id: str, idx: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            f"SELECT {_SEGMENT_SUMMARY_COLUMNS} FROM segments WHERE book_id = ? AND idx = ?",
            (book_id, idx),
        ).fetchone()
        return dict(row) if row else None

    def insert_many(self, segments: list[dict[str, Any]]) -> None:
        if not segments:
            return
        with db_transaction(self.conn):
            self.conn.executemany(
                """
                INSERT INTO segments (
                  id, book_id, idx, chapter, page_range, anchor_label,
                  raw_text, char_count, summary_status, retry_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        seg["id"],
                        seg["book_id"],
                        seg["idx"],
                        seg.get("chapter"),
                        seg.get("page_range"),
                        seg.get("anchor_label"),
                        seg["raw_text"],
                        seg.get("char_count", len(seg.get("raw_text") or "")),
                        seg.get("summary_status", "pending"),
                        seg.get("retry_count", 0),
                    )
                    for seg in segments
                ],
            )

    def update_summary(
        self,
        segment_id: str,
        *,
        summary_json: str,
        label: str,
        anchor_label: str | None = None,
        status: str = "ready",
        summary_provider: str | None = None,
        summary_model: str | None = None,
        summary_duration_s: float | None = None,
        summary_llm_attempts: int | None = None,
    ) -> None:
        with db_transaction(self.conn):
            self.conn.execute(
                """
                UPDATE segments SET summary_json = ?, label = ?, anchor_label = COALESCE(?, anchor_label),
                summary_status = ?, retry_count = 0,
                summary_provider = ?, summary_model = ?,
                summary_duration_s = ?, summary_llm_attempts = ?
                WHERE id = ?
                """,
                (
                    summary_json,
                    label,
                    anchor_label,
                    status,
                    summary_provider,
                    summary_model,
                    summary_duration_s,
                    summary_llm_attempts,
                    segment_id,
                ),
            )

    def set_status(self, segment_id: str, status: str, retry_count: int | None = None) -> None:
        with db_transaction(self.conn):
            if retry_count is None:
                self.conn.execute(
                    "UPDATE segments SET summary_status = ? WHERE id = ?",
                    (status, segment_id),
                )
            else:
                self.conn.execute(
                    "UPDATE segments SET summary_status = ?, retry_count = ? WHERE id = ?",
                    (status, retry_count, segment_id),
                )


class ChatRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get_or_create_session(self, book_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM chat_sessions WHERE book_id = ? ORDER BY updated_at DESC LIMIT 1",
            (book_id,),
        ).fetchone()
        if row:
            return dict(row)
        session_id = str(uuid.uuid4())
        now = _now()
        with db_transaction(self.conn):
            self.conn.execute(
                "INSERT INTO chat_sessions (id, book_id, scope, updated_at) VALUES (?, ?, ?, ?)",
                (session_id, book_id, "book", now),
            )
        return {"id": session_id, "book_id": book_id, "scope": "book", "updated_at": now}

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        citations_json: str | None = None,
        web_refs_json: str | None = None,
    ) -> dict[str, Any]:
        msg_id = str(uuid.uuid4())
        now = _now()
        with db_transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO chat_messages (id, session_id, role, content, citations_json, web_refs_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (msg_id, session_id, role, content, citations_json, web_refs_json, now),
            )
            self.conn.execute(
                "UPDATE chat_sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
        return {
            "id": msg_id,
            "session_id": session_id,
            "role": role,
            "content": content,
            "citations_json": citations_json,
            "web_refs_json": web_refs_json,
            "created_at": now,
        }

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]


_NOTE_LIST_SQL = """
SELECT
  n.id, n.book_id, n.segment_id, n.quote, n.content, n.type, n.created_at,
  s.idx AS segment_index,
  COALESCE(NULLIF(s.label, ''), s.anchor_label, '段 ' || (s.idx + 1)) AS segment_label,
  b.title AS book_title
FROM notes n
JOIN segments s ON s.id = n.segment_id
JOIN books b ON b.id = n.book_id
"""


class NoteRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create(
        self,
        *,
        book_id: str,
        content: str,
        segment_id: str,
        note_type: str = "manual",
        quote: str | None = None,
    ) -> dict[str, Any]:
        note_id = str(uuid.uuid4())
        now = _now()
        with db_transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO notes (id, book_id, segment_id, quote, content, type, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (note_id, book_id, segment_id, quote, content, note_type, now),
            )
        enriched = self._list(where="n.id = ?", params=(note_id,))
        return enriched[0]

    def list_for_book(
        self, book_id: str, *, segment_id: str | None = None
    ) -> list[dict[str, Any]]:
        if segment_id:
            return self._list(
                where="n.book_id = ? AND n.segment_id = ?",
                params=(book_id, segment_id),
            )
        return self._list(where="n.book_id = ?", params=(book_id,))

    def list_all(self) -> list[dict[str, Any]]:
        return self._list(where="1=1", params=())

    def get(self, note_id: str) -> dict[str, Any] | None:
        rows = self._list(where="n.id = ?", params=(note_id,))
        return rows[0] if rows else None

    def delete(self, note_id: str) -> bool:
        with db_transaction(self.conn):
            cur = self.conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            if cur.rowcount == 0:
                return False
            delete_note_from_fts(self.conn, note_id)
        return True

    def _list(self, *, where: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            f"{_NOTE_LIST_SQL} WHERE {where} ORDER BY n.created_at DESC",
            params,
        ).fetchall()
        return [dict(r) for r in rows]


class NewsChatRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def list_messages(self, article_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM news_chat_messages WHERE article_id = ? ORDER BY created_at",
            (article_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def add_message(
        self,
        article_id: str,
        role: str,
        content: str,
        *,
        web_refs_json: str | None = None,
    ) -> dict[str, Any]:
        msg_id = str(uuid.uuid4())
        now = _now()
        with db_transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO news_chat_messages (id, article_id, role, content, web_refs_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (msg_id, article_id, role, content, web_refs_json, now),
            )
        return {
            "id": msg_id,
            "article_id": article_id,
            "role": role,
            "content": content,
            "web_refs_json": web_refs_json,
            "created_at": now,
        }
