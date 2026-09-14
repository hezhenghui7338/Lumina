"""News article time ordering helpers (published_at, else synced_at)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class RankedArticle:
    article: dict[str, Any]
    score: float
    reasons: list[str]


def _parse_ts(raw: str | None) -> datetime | None:
    s = (raw or "").strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        if "T" in s:
            return datetime.fromisoformat(s)
        return datetime.fromisoformat(s[:10]).replace(tzinfo=timezone.utc)
    except Exception:
        return None


def article_time(article: dict[str, Any]) -> datetime | None:
    """Effective article time: published_at, else synced_at."""
    ts = _parse_ts(article.get("published_at")) or _parse_ts(article.get("synced_at"))
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def article_sort_key(article: dict[str, Any]) -> tuple[float, str]:
    """Newest-first sort key (timestamp, title)."""
    ts = article_time(article)
    epoch = ts.timestamp() if ts is not None else 0.0
    return (epoch, article.get("title") or "")


def score_article(article: dict[str, Any], *, now: datetime | None = None) -> RankedArticle:
    """Legacy score helper kept for tests; brief no longer ranks by score."""
    del now  # unused; freshness ranking removed from product sort
    return RankedArticle(article=article, score=0.0, reasons=[])


def rank_articles(
    articles: list[dict[str, Any]],
    *,
    limit: int | None = None,
) -> list[RankedArticle]:
    ranked = [score_article(a) for a in articles]
    ranked.sort(key=lambda r: article_sort_key(r.article), reverse=True)
    if limit is not None:
        return ranked[: max(0, limit)]
    return ranked
