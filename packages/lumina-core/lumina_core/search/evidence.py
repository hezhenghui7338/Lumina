"""Assemble web evidence for deep chat: search + fetch + URL paste."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field

from lumina_core.news.fetch import fetch_article
from lumina_core.search.web import (
    WebResult,
    assess_evidence_sufficiency,
    search_web,
)

WEB_EVIDENCE_RESERVE_CHARS = 2500
WEB_FETCH_TIMEOUT_SECONDS = 8.0
WEB_FETCH_MAX_PAGES = 2
WEB_FETCH_BODY_CHARS = 1200
WEB_SNIPPET_CHARS = 400

_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)
_DISABLED_PROVIDERS = frozenset({"none", "off", "disabled"})


@dataclass
class WebEvidence:
    refs: list[dict[str, str]] = field(default_factory=list)
    block: str = ""
    searched: bool = False


def extract_urls(text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for match in _URL_RE.findall(text or ""):
        url = match.rstrip(".,;:。，；")
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def strip_urls(text: str) -> str:
    return _URL_RE.sub(" ", text or "").strip()


def web_search_disabled(enabled: bool, provider: str | None) -> bool:
    if not enabled:
        return True
    return (provider or "").strip().lower() in _DISABLED_PROVIDERS


def will_use_web(
    message: str,
    local_context: str,
    *,
    enabled: bool = True,
    provider: str = "ddgs",
) -> bool:
    if web_search_disabled(enabled, provider):
        return False
    if extract_urls(message):
        return True
    question = strip_urls(message) or message
    return not assess_evidence_sufficiency(question, local_context)


def format_web_block(
    results: list[WebResult],
    fetched: list[tuple[str, str, str]],
    *,
    max_chars: int = WEB_EVIDENCE_RESERVE_CHARS,
) -> str:
    """Build a labeled web-evidence section. Caps at max_chars."""
    fetched_by_url = {url: (title, body) for url, title, body in fetched}
    parts: list[str] = ["## 联网检索"]
    used = len(parts[0]) + 2
    seen: set[str] = set()
    index = 0

    def _add(chunk: str) -> bool:
        nonlocal used
        if used >= max_chars:
            return False
        remaining = max_chars - used
        text = chunk if len(chunk) <= remaining else chunk[:remaining].rstrip()
        if not text:
            return False
        parts.append(text)
        used += len(text) + 2
        return len(chunk) <= remaining

    def _emit(url: str, title: str, source: str, snippet: str, body: str) -> None:
        nonlocal index
        if not url or url in seen:
            return
        seen.add(url)
        index += 1
        heading = title.strip() or url
        src = f" ({source})" if source else ""
        block = f"### [网 {index}] {heading}{src}\nURL: {url}"
        if snippet:
            block += f"\n摘要: {snippet[:WEB_SNIPPET_CHARS]}"
        if body:
            block += f"\n正文摘录:\n{body[:WEB_FETCH_BODY_CHARS]}"
        _add(block)

    for result in results:
        body = ""
        title = result.title
        if result.url in fetched_by_url:
            fetched_title, body = fetched_by_url[result.url]
            title = title or fetched_title
        _emit(result.url, title, result.source, result.snippet, body)

    for url, title, body in fetched:
        _emit(url, title, "fetch", "", body)

    if len(parts) == 1:
        return ""
    return "\n\n".join(parts)


async def fetch_page_excerpts(urls: list[str]) -> list[tuple[str, str, str]]:
    """Fetch up to WEB_FETCH_MAX_PAGES URLs; timeouts become empty."""
    targets = [u for u in urls if u][:WEB_FETCH_MAX_PAGES]
    if not targets:
        return []

    async def _one(url: str) -> tuple[str, str, str] | None:
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    fetch_article,
                    url,
                    timeout=WEB_FETCH_TIMEOUT_SECONDS,
                ),
                timeout=WEB_FETCH_TIMEOUT_SECONDS + 1.0,
            )
        except (asyncio.TimeoutError, Exception):
            return None
        text = (getattr(result, "text", None) or "").strip()
        if not text:
            return None
        title = (getattr(result, "title", None) or "").strip()
        final_url = (getattr(result, "url", None) or url).strip() or url
        return final_url, title, text[:WEB_FETCH_BODY_CHARS]

    gathered = await asyncio.gather(*[_one(u) for u in targets], return_exceptions=True)
    out: list[tuple[str, str, str]] = []
    for item in gathered:
        if isinstance(item, tuple) and item[2]:
            out.append(item)
    return out


async def prepare_web_evidence(
    message: str,
    local_context: str,
    *,
    enabled: bool = True,
    provider: str = "ddgs",
    tavily_api_key: str | None = None,
    max_chars: int = WEB_EVIDENCE_RESERVE_CHARS,
) -> WebEvidence:
    if web_search_disabled(enabled, provider):
        return WebEvidence()

    urls = extract_urls(message)
    question = strip_urls(message) or message
    search_needed = not assess_evidence_sufficiency(question, local_context)
    results: list[WebResult] = []
    if search_needed:
        try:
            results = await search_web(
                question,
                provider=provider,
                tavily_api_key=tavily_api_key,
            )
        except Exception:
            results = []

    fetch_targets: list[str] = []
    for url in urls:
        if url not in fetch_targets:
            fetch_targets.append(url)
    for result in results:
        if len(fetch_targets) >= WEB_FETCH_MAX_PAGES:
            break
        if result.url and result.url not in fetch_targets:
            fetch_targets.append(result.url)

    fetched: list[tuple[str, str, str]] = []
    if fetch_targets:
        try:
            fetched = await fetch_page_excerpts(fetch_targets)
        except Exception:
            fetched = []

    block = format_web_block(results, fetched, max_chars=max_chars)
    refs: list[dict[str, str]] = []
    seen: set[str] = set()

    def _push(title: str, url: str, source: str) -> None:
        if not url or url in seen:
            return
        seen.add(url)
        refs.append({"title": title or url, "url": url, "source": source})

    for result in results:
        _push(result.title, result.url, result.source)
    for url, title, _body in fetched:
        _push(title, url, "fetch")

    return WebEvidence(
        refs=refs,
        block=block,
        searched=bool(urls) or search_needed,
    )
