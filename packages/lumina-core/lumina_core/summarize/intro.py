"""Book-level AI intro from public encyclopedia / library sources."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from lumina_core.config import PromptsConfig, format_prompt, load_prompts_config
from lumina_core.models.router import ProfileModelRouter
from lumina_core.news.fetch import fetch_article
from lumina_core.search.web import WebResult, search_web
from lumina_core.summarize.schema import (
    SegmentSummary,
    parse_segment_summary,
    parse_segment_summary_minimal,
    validate_summary_richness,
)
from lumina_core.summarize.segment import summary_to_json

logger = logging.getLogger(__name__)

_SOURCE_TEXT_MAX = 12_000
_FETCH_BODY_MAX = 4_000
_FETCH_TIMEOUT = 20.0
_MAX_FETCH_PAGES = 3
_SEG0_SAMPLE_CHARS = 400


@dataclass(frozen=True)
class IntroCitation:
    title: str
    url: str
    source: str

    def as_dict(self) -> dict[str, str]:
        return {"title": self.title, "url": self.url, "source": self.source}


@dataclass
class IntroGenerateResult:
    status: str  # ready | skipped | failed
    source_text: str | None = None
    summary: SegmentSummary | None = None
    citations: list[IntroCitation] | None = None
    error: str | None = None


def build_intro_query(
    *,
    title: str,
    author: str | None,
    segment0_chapter: str | None = None,
    segment0_label: str | None = None,
    segment0_sample: str | None = None,
) -> str:
    parts: list[str] = []
    t = (title or "").strip()
    if t:
        parts.append(t)
    a = (author or "").strip()
    if a:
        parts.append(a)
    ch = (segment0_chapter or "").strip().lstrip("§").strip()
    if ch and ch not in t:
        parts.append(ch)
    lab = (segment0_label or "").strip()
    if lab and lab not in t:
        parts.append(lab)
    sample = (segment0_sample or "").strip()
    if sample and len(parts) < 2:
        parts.append(sample[:80])
    return " ".join(parts).strip() or "book"


def _prefer_intro_sources(results: list[WebResult]) -> list[WebResult]:
    """Wikipedia / Open Library first, then general search hits."""
    preferred: list[WebResult] = []
    rest: list[WebResult] = []
    seen: set[str] = set()
    for r in results:
        if not r.url or r.url in seen:
            continue
        seen.add(r.url)
        src = (r.source or "").lower()
        if "wikipedia" in src or "open library" in src:
            preferred.append(r)
        else:
            rest.append(r)
    return (preferred + rest)[:5]


async def collect_intro_sources(
    query: str,
    *,
    provider: str = "ddgs",
    tavily_api_key: str | None = None,
) -> tuple[str, list[IntroCitation]]:
    """Search Wikipedia + Open Library (+ optional general) and fetch bodies."""
    results: list[WebResult] = []
    try:
        results.extend(
            await search_web(
                query,
                domain="books",
                provider=provider,
                tavily_api_key=tavily_api_key,
            )
        )
    except Exception:
        logger.exception("intro books search failed")
    try:
        results.extend(
            await search_web(
                query,
                domain="general",
                provider=provider,
                tavily_api_key=tavily_api_key,
            )
        )
    except Exception:
        logger.exception("intro general search failed")

    ranked = _prefer_intro_sources(results)
    if not ranked:
        return "", []

    citations: list[IntroCitation] = []
    blocks: list[str] = []

    async def _fetch_one(item: WebResult) -> tuple[WebResult, str] | None:
        try:
            fetched = await asyncio.wait_for(
                asyncio.to_thread(
                    fetch_article,
                    item.url,
                    timeout=_FETCH_TIMEOUT,
                ),
                timeout=_FETCH_TIMEOUT + 2.0,
            )
        except (asyncio.TimeoutError, Exception):
            return None
        text = (getattr(fetched, "text", None) or "").strip()
        if not text:
            # Fall back to search snippet when fetch fails.
            snippet = (item.snippet or "").strip()
            if not snippet:
                return None
            return item, snippet
        return item, text[:_FETCH_BODY_MAX]

    gathered = await asyncio.gather(
        *[_fetch_one(r) for r in ranked[:_MAX_FETCH_PAGES]],
        return_exceptions=True,
    )
    for item in gathered:
        if not isinstance(item, tuple):
            continue
        result, body = item
        title = (result.title or "").strip() or result.url
        citations.append(
            IntroCitation(title=title, url=result.url, source=result.source or "")
        )
        src = result.source or "web"
        blocks.append(f"### {title} ({src})\nURL: {result.url}\n{body}")

    # If fetches failed but we still have snippets, use those.
    if not blocks:
        for result in ranked[:_MAX_FETCH_PAGES]:
            snippet = (result.snippet or "").strip()
            if not snippet:
                continue
            title = (result.title or "").strip() or result.url
            citations.append(
                IntroCitation(title=title, url=result.url, source=result.source or "")
            )
            blocks.append(
                f"### {title} ({result.source or 'web'})\nURL: {result.url}\n{snippet}"
            )

    source_text = "\n\n".join(blocks).strip()[:_SOURCE_TEXT_MAX]
    return source_text, citations


async def summarize_intro(
    router: ProfileModelRouter,
    *,
    title: str,
    author: str | None,
    source_text: str,
    target_language: str = "zh-CN",
    prompts: PromptsConfig | None = None,
) -> SegmentSummary:
    resolved = prompts or load_prompts_config()
    template = resolved.book_intro or ""
    if not template.strip():
        raise ValueError("book_intro prompt missing")
    prompt = format_prompt(
        template,
        title=title or "",
        author=(author or "").strip() or "未知",
        target_language=target_language,
        text=source_text[:_SOURCE_TEXT_MAX],
    )
    raw = await router.complete(prompt, profile="summarize", json_mode=True)
    try:
        summary = parse_segment_summary(raw)
        validate_summary_richness(summary, min_body_chars=20)
    except Exception:
        summary = parse_segment_summary_minimal(raw, fallback_anchor="AI导读")
    # Normalize book-level label/anchor regardless of model output.
    data = json.loads(summary_to_json(summary))
    data["label"] = "AI导读"
    data["anchor"] = "AI导读"
    return parse_segment_summary(json.dumps(data, ensure_ascii=False))


async def generate_book_intro(
    router: ProfileModelRouter,
    *,
    title: str,
    author: str | None = None,
    segment0_chapter: str | None = None,
    segment0_label: str | None = None,
    segment0_sample: str | None = None,
    web_search_enabled: bool = True,
    web_search_provider: str = "ddgs",
    tavily_api_key: str | None = None,
    target_language: str = "zh-CN",
    prompts: PromptsConfig | None = None,
) -> IntroGenerateResult:
    """Full intro pipeline. Caller persists status; never raises for skip paths."""
    if not web_search_enabled:
        return IntroGenerateResult(status="skipped")

    query = build_intro_query(
        title=title,
        author=author,
        segment0_chapter=segment0_chapter,
        segment0_label=segment0_label,
        segment0_sample=segment0_sample,
    )
    try:
        source_text, citations = await collect_intro_sources(
            query,
            provider=web_search_provider,
            tavily_api_key=tavily_api_key,
        )
    except Exception as exc:
        logger.exception("intro source collection failed")
        return IntroGenerateResult(status="failed", error=str(exc)[:500])

    if not source_text.strip():
        return IntroGenerateResult(status="skipped")

    try:
        summary = await summarize_intro(
            router,
            title=title,
            author=author,
            source_text=source_text,
            target_language=target_language,
            prompts=prompts,
        )
    except Exception as exc:
        logger.exception("intro summarize failed")
        return IntroGenerateResult(
            status="failed",
            source_text=source_text,
            citations=citations,
            error=str(exc)[:500],
        )

    return IntroGenerateResult(
        status="ready",
        source_text=source_text,
        summary=summary,
        citations=citations,
    )


def intro_public_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Shape for GET /books/{id}/intro and SSE events."""
    return {
        "book_id": row.get("book_id"),
        "status": row.get("status") or "idle",
        "source_text": row.get("source_text"),
        "summary": row.get("summary"),
        "citations": row.get("citations") or [],
        "error": row.get("error"),
        "updated_at": row.get("updated_at"),
    }


def segment0_sample_chars(raw_text: str | None, *, limit: int = _SEG0_SAMPLE_CHARS) -> str:
    text = (raw_text or "").strip()
    if not text:
        return ""
    return text[:limit]
