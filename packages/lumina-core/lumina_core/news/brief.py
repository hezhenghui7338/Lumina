"""Rule-based news brief — title + RSS excerpt, no LLM."""

from __future__ import annotations

from datetime import datetime, timezone

import sqlite3

from lumina_core.news.rank import rank_articles
from lumina_core.news.store import NewsSourceRepo, NewsStore
from lumina_core.news.summary_parse import parse_rss_summary, skim_is_rich


def _truncate_chars(text: str, limit: int) -> str:
    raw = (text or "").strip()
    if limit <= 0 or len(raw) <= limit:
        return raw
    return raw[: limit - 1] + "…"


def build_brief(conn: sqlite3.Connection, *, limit: int = 25) -> dict:
    # Pull a wider pool then rank by score_hint + freshness.
    pool = NewsStore(conn).list_all(limit=max(limit * 6, 150))
    ranked = rank_articles(pool, limit=limit)
    source_titles = {
        s["id"]: (s.get("title") or s.get("url") or s["id"])
        for s in NewsSourceRepo(conn).list_sources()
    }
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cards = []
    for r in ranked:
        a = r.article
        sid = a.get("source_id") or ""
        stitle = source_titles.get(sid, sid) if sid else None
        parsed = parse_rss_summary(a.get("rss_summary") or "")
        one_liner = (
            (a.get("one_liner") or "").strip()
            or parsed.one_liner
            or (a.get("excerpt") or "").strip()
        )
        detail = parsed.detail or ""
        if detail:
            detail = _truncate_chars(detail, 360)
        viewpoints = (parsed.viewpoints or [])[:5]
        quotes = (parsed.quotes or [])[:6]
        meta = dict(parsed.meta or {})
        if a.get("author") and not meta.get("author"):
            meta["author"] = str(a["author"])
        cards.append(
            {
                "id": a["id"],
                "title": a["title"],
                "excerpt": one_liner or a.get("excerpt"),
                "one_liner": one_liner or None,
                "detail": detail or None,
                "viewpoints": viewpoints,
                "quotes": quotes,
                "meta": meta,
                "reasons": list(r.reasons),
                "score_hint": a.get("score_hint"),
                "source_id": sid or None,
                "source_title": stitle,
                "source": stitle,
                "url": a["url"],
                "published_at": a.get("published_at"),
                "skim_rich": skim_is_rich(parsed, detail=detail or None),
                "summary_status": a.get("summary_status") or "idle",
            }
        )
    return {"date": day, "count": len(cards), "articles": cards}
