"""Web search tests."""

from unittest.mock import AsyncMock, patch

import pytest

from lumina_core.search.web import (
    WebResult,
    assess_evidence_sufficiency,
    classify_domain,
    search_web,
)
from lumina_core.settings_store import (
    normalize_web_search_provider,
    resolve_web_search_provider,
)


def test_classify_domain():
    assert classify_domain("arxiv machine learning paper") == "academic"
    assert classify_domain("github repo python") == "code"
    assert classify_domain("作者是谁") == "books"


def test_evidence_insufficient_on_short_context():
    assert not assess_evidence_sufficiency("历史上发生了什么？", "短")


def test_evidence_sufficient_on_long_context():
    ctx = "x" * 500
    assert assess_evidence_sufficiency("总结本段", ctx)


def test_normalize_web_search_provider():
    assert normalize_web_search_provider("ddgs") == "ddgs"
    assert normalize_web_search_provider("Tavily") == "tavily"
    assert normalize_web_search_provider("nope") == "ddgs"
    assert normalize_web_search_provider(None) == "ddgs"


def test_resolve_falls_back_without_tavily_key():
    assert resolve_web_search_provider("tavily", None) == "ddgs"
    assert resolve_web_search_provider("tavily", "") == "ddgs"
    assert resolve_web_search_provider("tavily", "tvly-x") == "tavily"
    assert resolve_web_search_provider("ddgs", "tvly-x") == "ddgs"


@pytest.mark.asyncio
async def test_search_web_uses_ddgs_by_default():
    fake = [WebResult(title="A", url="https://a.example", snippet="", source="ddgs")]
    with patch("lumina_core.search.web._search_ddgs", new_callable=AsyncMock, return_value=fake):
        with patch("lumina_core.search.web._search_wikipedia", new_callable=AsyncMock, return_value=[]):
            results = await search_web("Python programming", provider="ddgs")
    assert len(results) == 1
    assert results[0].source == "ddgs"


@pytest.mark.asyncio
async def test_search_web_uses_tavily_when_configured():
    fake = [WebResult(title="B", url="https://b.example", snippet="x", source="Tavily")]
    with patch(
        "lumina_core.search.web._search_tavily", new_callable=AsyncMock, return_value=fake
    ) as mock_tavily:
        with patch("lumina_core.search.web._search_wikipedia", new_callable=AsyncMock, return_value=[]):
            results = await search_web(
                "Python programming",
                provider="tavily",
                tavily_api_key="tvly-test",
            )
    mock_tavily.assert_awaited_once()
    assert results[0].source == "Tavily"
