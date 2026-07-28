"""Rule-based news brief — title + RSS excerpt, no LLM."""

from __future__ import annotations

from datetime import datetime, timezone

import sqlite3

from lumina_core.news.store import NewsStore


def build_brief(conn: sqlite3.Connection, *, limit: int = 20) -> dict:
    articles = NewsStore(conn).list_recent(limit=limit)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cards = [
        {
            "id": a["id"],
            "title": a["title"],
            "excerpt": a["excerpt"],
            "source": a.get("source_id"),
            "url": a["url"],
            "published_at": a.get("published_at"),
        }
        for a in articles
    ]
    return {"date": day, "count": len(cards), "articles": cards}
