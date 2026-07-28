"""RSS sync."""

from __future__ import annotations

from dataclasses import dataclass

import sqlite3

from lumina_core.news.rss import fetch_feed, parse_feed
from lumina_core.news.store import NewsSourceRepo, NewsStore


@dataclass
class SyncResult:
    source_url: str
    fetched: int
    inserted: int
    error: str = ""


def sync_all(conn: sqlite3.Connection) -> list[SyncResult]:
    sources = NewsSourceRepo(conn).list_sources()
    store = NewsStore(conn)
    results: list[SyncResult] = []
    for src in sources:
        url = src["url"]
        try:
            raw = fetch_feed(url)
            articles = parse_feed(raw, source_id=src["id"])
            inserted = sum(1 for a in articles if store.upsert(a))
            results.append(
                SyncResult(source_url=url, fetched=len(articles), inserted=inserted)
            )
        except Exception as exc:
            results.append(
                SyncResult(source_url=url, fetched=0, inserted=0, error=str(exc))
            )
    return results
