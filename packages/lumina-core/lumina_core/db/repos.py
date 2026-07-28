"""Data access layer."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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

    def list_books(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM books ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]

    def insert(self, **fields: Any) -> dict[str, Any]:
        book_id = fields.get("id") or str(uuid.uuid4())
        now = _now()
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
                fields.get("status", "processing"),
                fields.get("file_hash"),
                json.dumps(fields.get("metadata_json") or {}, ensure_ascii=False),
                now,
                now,
            ),
        )
        self.conn.commit()
        return self.get(book_id)  # type: ignore[return-value]

    def update(self, book_id: str, **fields: Any) -> None:
        fields["updated_at"] = _now()
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(
            f"UPDATE books SET {cols} WHERE id = ?",
            (*fields.values(), book_id),
        )
        self.conn.commit()

    def delete(self, book_id: str) -> None:
        self.conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
        self.conn.commit()


class SegmentRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def list_for_book(self, book_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM segments WHERE book_id = ? ORDER BY idx",
            (book_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_by_index(self, book_id: str, idx: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM segments WHERE book_id = ? AND idx = ?",
            (book_id, idx),
        ).fetchone()
        return dict(row) if row else None

    def insert_many(self, segments: list[dict[str, Any]]) -> None:
        for seg in segments:
            self.conn.execute(
                """
                INSERT INTO segments (
                  id, book_id, idx, chapter, page_range, anchor_label,
                  raw_text, summary_status, retry_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    seg["id"],
                    seg["book_id"],
                    seg["idx"],
                    seg.get("chapter"),
                    seg.get("page_range"),
                    seg.get("anchor_label"),
                    seg["raw_text"],
                    seg.get("summary_status", "pending"),
                    seg.get("retry_count", 0),
                ),
            )
        self.conn.commit()

    def update_summary(
        self,
        segment_id: str,
        *,
        summary_json: str,
        label: str,
        anchor_label: str | None = None,
        status: str = "ready",
    ) -> None:
        self.conn.execute(
            """
            UPDATE segments SET summary_json = ?, label = ?, anchor_label = COALESCE(?, anchor_label),
            summary_status = ?, retry_count = 0 WHERE id = ?
            """,
            (summary_json, label, anchor_label, status, segment_id),
        )
        self.conn.commit()

    def set_status(self, segment_id: str, status: str, retry_count: int | None = None) -> None:
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
        self.conn.commit()


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
        self.conn.execute(
            "INSERT INTO chat_sessions (id, book_id, scope, updated_at) VALUES (?, ?, ?, ?)",
            (session_id, book_id, "book", now),
        )
        self.conn.commit()
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
        self.conn.commit()
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


class NoteRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create(
        self,
        *,
        book_id: str,
        content: str,
        note_type: str = "manual",
        segment_id: str | None = None,
        quote: str | None = None,
    ) -> dict[str, Any]:
        note_id = str(uuid.uuid4())
        now = _now()
        self.conn.execute(
            """
            INSERT INTO notes (id, book_id, segment_id, quote, content, type, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (note_id, book_id, segment_id, quote, content, note_type, now),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        return dict(row)  # type: ignore[return-value]

    def list_for_book(self, book_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM notes WHERE book_id = ? ORDER BY created_at DESC",
            (book_id,),
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
        self.conn.execute(
            """
            INSERT INTO news_chat_messages (id, article_id, role, content, web_refs_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (msg_id, article_id, role, content, web_refs_json, now),
        )
        self.conn.commit()
        return {
            "id": msg_id,
            "article_id": article_id,
            "role": role,
            "content": content,
            "web_refs_json": web_refs_json,
            "created_at": now,
        }
