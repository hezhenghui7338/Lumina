"""Interest ranking for news brief (score_hint + freshness; empty profile by default)."""

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


def _freshness_boost(article: dict[str, Any], *, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    ts = _parse_ts(article.get("published_at")) or _parse_ts(article.get("synced_at"))
    if not ts:
        return 0.0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    hours = max(0.0, (now - ts).total_seconds() / 3600.0)
    if hours <= 24:
        return 3.0
    if hours <= 72:
        return 1.5
    if hours <= 168:
        return 0.5
    return 0.0


def score_article(article: dict[str, Any], *, now: datetime | None = None) -> RankedArticle:
    score = 0.0
    reasons: list[str] = []

    fresh = _freshness_boost(article, now=now)
    if fresh:
        score += fresh
        reasons.append("新鲜")

    hint = article.get("score_hint")
    if hint is not None:
        try:
            score += float(hint) / 50.0
            reasons.append(f"质量提示:{int(float(hint))}")
        except (TypeError, ValueError):
            pass

    if not reasons:
        reasons.append("默认候选")

    return RankedArticle(article=article, score=score, reasons=reasons)


def rank_articles(
    articles: list[dict[str, Any]],
    *,
    limit: int | None = None,
) -> list[RankedArticle]:
    ranked = [score_article(a) for a in articles]
    ranked.sort(
        key=lambda r: (
            r.score,
            r.article.get("published_at") or "",
            r.article.get("title") or "",
        ),
        reverse=True,
    )
    if limit is not None:
        return ranked[: max(0, limit)]
    return ranked
