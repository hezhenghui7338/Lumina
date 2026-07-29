"""RSS fetch and parse."""

from __future__ import annotations

import re
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

import feedparser
import httpx

from lumina_core.news.store import NewsArticle, article_id_for_url
from lumina_core.news.summary_parse import parse_rss_summary, score_hint_from_parsed

_HTML_TAG = re.compile(r"<[^>]+>")


@dataclass
class FeedItem:
    url: str
    title: str
    summary: str
    author: str
    published_at: str


def strip_html(text: str) -> str:
    cleaned = _HTML_TAG.sub(" ", text or "")
    return " ".join(cleaned.split()).strip()


def excerpt_from_summary(text: str, *, limit: int = 220) -> str:
    raw = strip_html(text)
    if len(raw) <= limit:
        return raw
    return raw[: limit - 1] + "…"


def fetch_feed(url: str, *, timeout: float = 30.0) -> bytes:
    headers = {
        "User-Agent": "Lumina/0.1 (+https://github.com/lumina)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    }
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.content


def parse_feed(raw: bytes, *, source_id: str) -> list[NewsArticle]:
    parsed = feedparser.parse(raw)
    articles: list[NewsArticle] = []
    for entry in parsed.entries:
        link = getattr(entry, "link", None) or entry.get("link") if hasattr(entry, "get") else None
        if not link:
            continue
        title = getattr(entry, "title", "") or ""
        summary = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
        author = ""
        if getattr(entry, "author", None):
            author = str(entry.author)
        published = ""
        for key in ("published", "updated"):
            raw_date = getattr(entry, key, None)
            if raw_date:
                try:
                    published = parsedate_to_datetime(str(raw_date)).strftime("%Y-%m-%dT%H:%M:%SZ")
                except Exception:
                    published = str(raw_date)[:19]
                break

        plain = strip_html(summary)
        parsed_sum = parse_rss_summary(plain)
        one_liner = parsed_sum.one_liner
        excerpt = one_liner or excerpt_from_summary(summary)
        score_hint = score_hint_from_parsed(parsed_sum)
        if not author and parsed_sum.meta.get("author"):
            author = parsed_sum.meta["author"]

        articles.append(
            NewsArticle(
                id=article_id_for_url(link),
                source_id=source_id,
                url=link,
                title=strip_html(title),
                excerpt=excerpt,
                author=author,
                published_at=published,
                rss_summary=plain,
                one_liner=one_liner,
                score_hint=score_hint,
            )
        )
    return articles
