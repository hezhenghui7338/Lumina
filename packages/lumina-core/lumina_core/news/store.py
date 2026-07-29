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
    rss_summary: str = ""
    one_liner: str = ""
    score_hint: float | None = None
    fetched_text_path: str = ""
    summary_markdown: str = ""
    summary_status: str = "idle"


class NewsStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def upsert(self, article: NewsArticle) -> bool:
        existing = self.conn.execute(
            "SELECT id FROM news_articles WHERE id = ?", (article.id,)
        ).fetchone()
        self.conn.execute(
            """
            INSERT INTO news_articles (
              id, source_id, url, title, excerpt, author, published_at, synced_at,
              rss_summary, one_liner, score_hint, fetched_text_path,
              summary_markdown, summary_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              title=excluded.title,
              excerpt=excluded.excerpt,
              author=excluded.author,
              published_at=excluded.published_at,
              synced_at=excluded.synced_at,
              rss_summary=excluded.rss_summary,
              one_liner=excluded.one_liner,
              score_hint=excluded.score_hint
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
                article.rss_summary,
                article.one_liner,
                article.score_hint,
                article.fetched_text_path or None,
                article.summary_markdown or None,
                article.summary_status or "idle",
            ),
        )
        self.conn.commit()
        return existing is None

    def update_fields(self, article_id: str, **fields: Any) -> None:
        if not fields:
            return
        allowed = {
            "title",
            "excerpt",
            "author",
            "published_at",
            "rss_summary",
            "one_liner",
            "score_hint",
            "fetched_text_path",
            "summary_markdown",
            "summary_status",
        }
        cols = []
        vals: list[Any] = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            cols.append(f"{key}=?")
            vals.append(value)
        if not cols:
            return
        vals.append(article_id)
        self.conn.execute(
            f"UPDATE news_articles SET {', '.join(cols)} WHERE id = ?",
            vals,
        )
        self.conn.commit()

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

    def list_all(self, *, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM news_articles
            ORDER BY synced_at DESC
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

    def get_by_url(self, url: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM news_sources WHERE url = ?", (url,)
        ).fetchone()
        return dict(row) if row else None

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

    def prune_obsolete_presets(self, obsolete_urls: frozenset[str]) -> int:
        """Delete retired preset sources and their articles. Custom URLs untouched."""
        if not obsolete_urls:
            return 0
        placeholders = ",".join("?" * len(obsolete_urls))
        rows = self.conn.execute(
            f"SELECT id FROM news_sources WHERE url IN ({placeholders})",
            tuple(obsolete_urls),
        ).fetchall()
        pruned = 0
        for row in rows:
            source_id = row["id"]
            self.conn.execute(
                "DELETE FROM news_articles WHERE source_id = ?",
                (source_id,),
            )
            self.conn.execute(
                "DELETE FROM news_sources WHERE id = ?",
                (source_id,),
            )
            pruned += 1
        if pruned:
            self.conn.commit()
        return pruned

    def restore_defaults(self, urls: list[tuple[str, str]]) -> int:
        """Insert missing preset URLs and refresh preset titles. Returns change count."""
        restored = 0
        by_url = {r["url"]: r for r in self.list_sources()}
        for url, title in urls:
            row = by_url.get(url)
            if row is None:
                self.add_source(url, title)
                restored += 1
            elif title and (row.get("title") or "") != title:
                self.conn.execute(
                    "UPDATE news_sources SET title = ? WHERE url = ?",
                    (title, url),
                )
                self.conn.commit()
                restored += 1
        return restored

    def ensure_defaults(self, urls: list[tuple[str, str]]) -> None:
        self.restore_defaults(urls)
        from lumina_core.app_state import OBSOLETE_NEWS_SOURCE_URLS

        self.prune_obsolete_presets(OBSOLETE_NEWS_SOURCE_URLS)
