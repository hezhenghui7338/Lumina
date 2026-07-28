"""News article store."""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def article_id_for_url(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


@dataclass
class NewsArticle:
    id: str
    source_id: str
    url: str
    title: str
    excerpt: str
    author: str = ""
    published_at: str = ""


class NewsStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def upsert(self, article: NewsArticle) -> bool:
        existing = self.conn.execute(
            "SELECT id FROM news_articles WHERE id = ?", (article.id,)
        ).fetchone()
        self.conn.execute(
            """
            INSERT INTO news_articles (id, source_id, url, title, excerpt, author, published_at, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              title=excluded.title,
              excerpt=excluded.excerpt,
              author=excluded.author,
              published_at=excluded.published_at,
              synced_at=excluded.synced_at
            """,
            (
                article.id,
                article.source_id,
                article.url,
                article.title,
                article.excerpt,
                article.author,
                article.published_at,
                _now(),
            ),
        )
        self.conn.commit()
        return existing is None

    def list_recent(self, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM news_articles
            ORDER BY published_at DESC, synced_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get(self, article_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM news_articles WHERE id = ?", (article_id,)
        ).fetchone()
        return dict(row) if row else None


class NewsSourceRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def list_sources(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM news_sources ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]

    def add_source(self, url: str, title: str = "") -> dict[str, Any]:
        source_id = str(uuid.uuid4())
        now = _now()
        self.conn.execute(
            """
            INSERT INTO news_sources (id, url, title, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (source_id, url, title or url, now),
        )
        self.conn.commit()
        return {"id": source_id, "url": url, "title": title or url, "created_at": now}

    def delete_source(self, source_id: str) -> None:
        self.conn.execute("DELETE FROM news_sources WHERE id = ?", (source_id,))
        self.conn.commit()

    def ensure_defaults(self, urls: list[tuple[str, str]]) -> None:
        existing = {r["url"] for r in self.list_sources()}
        for url, title in urls:
            if url not in existing:
                self.add_source(url, title)
