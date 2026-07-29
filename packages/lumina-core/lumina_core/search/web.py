"""Evidence-sufficiency driven web search — reference LA web_search subset."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote_plus

import httpx

from lumina_core.settings_store import resolve_web_search_provider

_USER_AGENT = "Lumina/0.1 (https://github.com/hezhenghui7338/Lumina; bot@lumina.ai)"

Domain = Literal["general", "academic", "books", "code"]


@dataclass(frozen=True)
class WebResult:
    title: str
    url: str
    snippet: str
    source: str


def classify_domain(query: str) -> Domain:
    q = query.lower()
    if any(k in q for k in ("arxiv", "论文", "paper", "research", "study")):
        return "academic"
    if any(k in q for k in ("github", "repo", "代码", "开源", "library api")):
        return "code"
    if any(k in q for k in ("作者", "书名", "出版", "author", "isbn", "open library")):
        return "books"
    return "general"


def assess_evidence_sufficiency(
    query: str,
    local_context: str,
    *,
    min_chars: int = 200,
) -> bool:
    """Return True if local context is likely sufficient (skip web)."""
    ctx = (local_context or "").strip()
    if len(ctx) < min_chars:
        return False
    # Simple heuristic: question asks for external facts
    external_markers = (
        "历史上",
        "背景",
        "为什么",
        "维基",
        "网上",
        "最新",
        "who is",
        "when did",
        "wikipedia",
    )
    q = query.lower()
    if any(m in query or m in q for m in external_markers):
        return False
    return True


def _query_has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


async def search_web(
    query: str,
    domain: Domain | None = None,
    *,
    provider: str = "ddgs",
    tavily_api_key: str | None = None,
) -> list[WebResult]:
    domain = domain or classify_domain(query)
    results: list[WebResult] = []
    resolved = resolve_web_search_provider(provider, tavily_api_key)

    if domain in ("general", "academic", "books", "code"):
        if resolved == "tavily":
            results.extend(await _search_tavily(query, tavily_api_key or ""))
        else:
            results.extend(await _search_ddgs(query))

    if domain == "academic":
        results.extend(await _search_arxiv(query))
    if domain == "books":
        results.extend(await _search_open_library(query))
    if domain == "code":
        results.extend(await _search_github(query))
    if domain == "general":
        results.extend(await _search_wikipedia(query))

    seen: set[str] = set()
    deduped: list[WebResult] = []
    for r in results:
        if not r.url or r.url in seen:
            continue
        seen.add(r.url)
        deduped.append(r)
    return deduped[:5]


async def _search_ddgs(query: str, *, max_results: int = 3) -> list[WebResult]:
    def _run() -> list[WebResult]:
        try:
            from ddgs import DDGS
        except ImportError:
            return []
        kwargs: dict = {"max_results": max_results}
        if _query_has_cjk(query):
            kwargs["region"] = "cn-zh"
        try:
            with DDGS() as ddgs:
                raw = list(ddgs.text(query, **kwargs))
        except Exception:
            return []
        out: list[WebResult] = []
        for item in raw:
            url = item.get("href") or item.get("url") or ""
            if not url:
                continue
            out.append(
                WebResult(
                    title=(item.get("title") or "").strip(),
                    url=url,
                    snippet=(item.get("body") or "")[:200],
                    source="ddgs",
                )
            )
        return out

    return await asyncio.to_thread(_run)


async def _search_tavily(query: str, api_key: str, *, max_results: int = 5) -> list[WebResult]:
    if not api_key.strip():
        return []
    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post("https://api.tavily.com/search", json=payload)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, KeyError, json.JSONDecodeError):
        return []
    out: list[WebResult] = []
    for item in data.get("results") or []:
        url = item.get("url") or ""
        if not url:
            continue
        out.append(
            WebResult(
                title=(item.get("title") or "").strip(),
                url=url,
                snippet=(item.get("content") or "")[:200],
                source="Tavily",
            )
        )
    return out[:max_results]


async def _search_wikipedia(query: str) -> list[WebResult]:
    api = "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "format": "json",
        "utf8": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                api,
                params=params,
                headers={"User-Agent": _USER_AGENT},
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
    except (httpx.HTTPError, KeyError, json.JSONDecodeError):
        return []
    out: list[WebResult] = []
    for item in data.get("query", {}).get("search", [])[:2]:
        title = item.get("title", "")
        out.append(
            WebResult(
                title=title,
                url=f"https://en.wikipedia.org/wiki/{quote_plus(title.replace(' ', '_'))}",
                snippet=item.get("snippet", ""),
                source="Wikipedia",
            )
        )
    return out


async def _search_arxiv(query: str) -> list[WebResult]:
    url = f"https://export.arxiv.org/api/query?search_query=all:{quote_plus(query)}&max_results=2"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            text = resp.text
    except httpx.HTTPError:
        return []
    out: list[WebResult] = []
    for entry in re.findall(r"<entry>(.*?)</entry>", text, re.DOTALL)[:2]:
        title_m = re.search(r"<title>(.*?)</title>", entry, re.DOTALL)
        id_m = re.search(r"<id>(.*?)</id>", entry)
        if title_m and id_m:
            out.append(
                WebResult(
                    title=re.sub(r"\s+", " ", title_m.group(1)).strip(),
                    url=id_m.group(1).strip(),
                    snippet="",
                    source="arXiv",
                )
            )
    return out


async def _search_open_library(query: str) -> list[WebResult]:
    url = f"https://openlibrary.org/search.json?q={quote_plus(query)}&limit=2"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            docs = resp.json().get("docs", [])
    except (httpx.HTTPError, KeyError):
        return []
    out: list[WebResult] = []
    for doc in docs[:2]:
        title = doc.get("title", "Unknown")
        key = doc.get("key", "")
        out.append(
            WebResult(
                title=title,
                url=f"https://openlibrary.org{key}",
                snippet=", ".join(doc.get("author_name", [])[:2]),
                source="Open Library",
            )
        )
    return out


async def _search_github(query: str) -> list[WebResult]:
    url = f"https://api.github.com/search/repositories?q={quote_plus(query)}&per_page=2"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": _USER_AGENT,
                },
            )
            items = resp.json().get("items", [])
    except (httpx.HTTPError, KeyError):
        return []
    return [
        WebResult(
            title=item.get("full_name", ""),
            url=item.get("html_url", ""),
            snippet=(item.get("description") or "")[:200],
            source="GitHub",
        )
        for item in items[:2]
    ]
