"""Deep-read an article: fetch → summarize card."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import sqlite3

from lumina_core.models.router import ProfileModelRouter
from lumina_core.news.fetch import FetchResult, body_quality_ok, fetch_article
from lumina_core.news.store import NewsStore
from lumina_core.news.summary_parse import parse_rss_summary
from lumina_core.summarize.document import (
    omit_misleading_asks,
    summarize_document,
)


@dataclass
class ReadResult:
    article: dict[str, Any]
    summary_markdown: str = ""
    warnings: list[str] = field(default_factory=list)
    error: str = ""
    body_complete: bool = True
    body_text: str = ""


def _expected_word_count(article: dict[str, Any]) -> int | None:
    parsed = parse_rss_summary(article.get("rss_summary") or "")
    raw = (parsed.meta or {}).get("word_count") or ""
    try:
        val = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return val if val > 0 else None


def _origin_hints(article: dict[str, Any]) -> list[str]:
    parsed = parse_rss_summary(article.get("rss_summary") or "")
    source = (parsed.meta or {}).get("source") or ""
    if source.startswith(("http://", "https://")):
        return [source.strip()]
    return []


def _rss_fallback_body(article: dict[str, Any]) -> tuple[str, list[str]]:
    parsed = parse_rss_summary(article.get("rss_summary") or "")
    parts: list[str] = []
    if parsed.one_liner:
        parts.append(parsed.one_liner)
    if parsed.detail:
        parts.append(parsed.detail)
    if parsed.viewpoints:
        parts.append("主要观点：\n" + "\n".join(f"- {v}" for v in parsed.viewpoints))
    if parsed.quotes:
        parts.append("金句：\n" + "\n".join(f"- {q}" for q in parsed.quotes))
    body = "\n\n".join(p for p in parts if p.strip()).strip()
    if not body and article.get("excerpt"):
        body = str(article["excerpt"])
    warnings = [
        "未拿到完整正文，已用 RSS 摘要降级；深聊仅基于摘要，细节可能不足"
    ]
    return body, warnings


def _strip_cache_meta(raw: str) -> tuple[str, str]:
    text = raw or ""
    title = ""
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break
    body = text
    if body.startswith("# "):
        parts = body.split("\n\n", 2)
        if len(parts) == 3 and parts[1].startswith("来源:"):
            body = parts[2]
        elif len(parts) >= 2:
            body = "\n\n".join(parts[1:])
    return title, body.strip()


def _write_cache(cache_path: Path, title: str, url: str, body: str) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        f"# {title}\n\n来源: {url}\n\n{body}",
        encoding="utf-8",
    )


def load_cached_body(article: dict[str, Any]) -> str:
    path = (article.get("fetched_text_path") or "").strip()
    if not path:
        return ""
    p = Path(path)
    if not p.exists():
        return ""
    _, body = _strip_cache_meta(p.read_text(encoding="utf-8"))
    return body


async def read_article(
    conn: sqlite3.Connection,
    router: ProfileModelRouter,
    article_id: str,
    *,
    cache_dir: Path,
    force_refetch: bool = False,
    use_llm: bool = True,
) -> ReadResult:
    store = NewsStore(conn)
    article = store.get(article_id)
    if not article:
        return ReadResult(article={}, error="Article not found")

    if article.get("summary_status") == "running":
        store.update_fields(article_id, summary_status="pending")
        article = store.get(article_id) or article

    store.update_fields(article_id, summary_status="running")
    warnings: list[str] = []
    body_complete = True
    title = article.get("title") or ""
    body_for_sum = ""
    expected = _expected_word_count(article)
    cache_path = cache_dir / f"{article_id}.md"

    use_cache = cache_path.exists() and not force_refetch
    if use_cache:
        raw_body = cache_path.read_text(encoding="utf-8")
        cached_title, cached_body = _strip_cache_meta(raw_body)
        if cached_title:
            title = cached_title
        if body_quality_ok(cached_body, expected_word_count=expected):
            body_for_sum = cached_body
        else:
            use_cache = False
            warnings.append("缓存正文过短，已重新抓取")

    if not body_for_sum:
        fetched: FetchResult = await asyncio.to_thread(
            fetch_article,
            article["url"],
            expected_word_count=expected,
            origin_hints=_origin_hints(article),
        )
        warnings.extend(fetched.warnings)
        if fetched.ok and body_quality_ok(fetched.text, expected_word_count=expected):
            body_for_sum = fetched.text
            if fetched.title:
                title = fetched.title
            _write_cache(cache_path, title or article["title"], article["url"], body_for_sum)
            store.update_fields(
                article_id,
                title=title or article["title"],
                fetched_text_path=str(cache_path),
            )
        elif fetched.text and body_quality_ok(
            fetched.text, min_chars=max(200, 250)
        ):
            body_for_sum = fetched.text
            body_complete = False
            if fetched.title:
                title = fetched.title
            warnings.append(
                f"正文偏短（约 {len(fetched.text)} 字），可能不完整；{fetched.error or '质量门控未完全通过'}"
            )
            _write_cache(cache_path, title or article["title"], article["url"], body_for_sum)
            store.update_fields(
                article_id,
                title=title or article["title"],
                fetched_text_path=str(cache_path),
            )
        else:
            rss_body, rss_warns = _rss_fallback_body(article)
            if not rss_body:
                err = fetched.error or "未能抽取正文"
                store.update_fields(article_id, summary_status="failed")
                return ReadResult(
                    article=store.get(article_id) or article,
                    error=err,
                    warnings=warnings,
                )
            body_for_sum = rss_body
            body_complete = False
            warnings.extend(rss_warns)
            if fetched.error:
                warnings.append(fetched.error)
            _write_cache(cache_path, title or article["title"], article["url"], body_for_sum)
            store.update_fields(
                article_id,
                title=title or article["title"],
                fetched_text_path=str(cache_path),
            )

    try:
        result = await summarize_document(
            router,
            text=f"# {title}\n\n{body_for_sum}",
            title=title or article_id,
            use_llm=use_llm,
            allow_long=True,
        )
    except Exception as exc:
        store.update_fields(article_id, summary_status="failed")
        return ReadResult(
            article=store.get(article_id) or article,
            error=str(exc),
            warnings=warnings,
            body_text=body_for_sum,
        )

    warnings = list(dict.fromkeys([*warnings, *result.warnings]))
    card = omit_misleading_asks(result.markdown, body_complete=body_complete)
    store.update_fields(
        article_id,
        title=title or article["title"],
        fetched_text_path=str(cache_path),
        summary_markdown=card,
        summary_status="ready",
    )
    refreshed = store.get(article_id) or article
    return ReadResult(
        article=refreshed,
        summary_markdown=card,
        warnings=warnings,
        body_complete=body_complete,
        body_text=body_for_sum,
    )
