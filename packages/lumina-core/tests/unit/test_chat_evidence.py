"""Web evidence assembly for deep chat."""

from unittest.mock import AsyncMock, patch

import pytest

from lumina_core.search.evidence import (
    extract_urls,
    format_web_block,
    prepare_web_evidence,
    will_use_web,
)
from lumina_core.search.web import WebResult, assess_evidence_sufficiency


def test_extract_urls_strips_punctuation():
    text = "参考 https://example.com/a, 以及 http://foo.test/b。"
    assert extract_urls(text) == ["https://example.com/a", "http://foo.test/b"]


def test_will_use_web_for_pasted_url():
    assert will_use_web("看看 https://example.com/wiki", "足够长的本地上下文" * 20)


def test_will_use_web_skips_when_disabled():
    assert not will_use_web(
        "历史上发生了什么？",
        "短",
        enabled=False,
    )
    assert not will_use_web("https://example.com", "ctx", provider="none")


def test_format_web_block_includes_snippet_and_body():
    results = [
        WebResult(title="牛顿", url="https://zh.wikipedia.org/wiki/牛顿", snippet="物理学家", source="Wikipedia")
    ]
    fetched = [("https://zh.wikipedia.org/wiki/牛顿", "牛顿", "艾萨克·牛顿提出三大定律。")]
    block = format_web_block(results, fetched)
    assert "## 联网检索" in block
    assert "摘要: 物理学家" in block
    assert "正文摘录:" in block
    assert "三大定律" in block
    assert "https://zh.wikipedia.org/wiki/牛顿" in block


@pytest.mark.asyncio
async def test_prepare_web_evidence_fetches_user_url():
    with (
        patch("lumina_core.search.evidence.search_web", new=AsyncMock(return_value=[])),
        patch(
            "lumina_core.search.evidence.fetch_page_excerpts",
            new=AsyncMock(return_value=[("https://example.com/x", "标题", "网页正文摘录")]),
        ),
    ):
        ctx = "本段讲述主角赶考。" * 30
        evidence = await prepare_web_evidence(
            "对照一下 https://example.com/x",
            ctx,
        )
    assert evidence.refs
    assert evidence.refs[0]["url"] == "https://example.com/x"
    assert "网页正文摘录" in evidence.block


@pytest.mark.asyncio
async def test_prepare_web_evidence_disabled_returns_empty():
    evidence = await prepare_web_evidence(
        "历史上发生了什么？",
        "短",
        enabled=False,
    )
    assert evidence.refs == []
    assert evidence.block == ""


@pytest.mark.asyncio
async def test_prepare_web_evidence_fetch_timeout_falls_back_to_snippets():
    with (
        patch(
            "lumina_core.search.evidence.search_web",
            new=AsyncMock(
                return_value=[
                    WebResult(title="条目", url="https://example.com/a", snippet="摘要句", source="ddgs")
                ]
            ),
        ),
        patch(
            "lumina_core.search.evidence.fetch_page_excerpts",
            new=AsyncMock(return_value=[]),
        ),
    ):
        evidence = await prepare_web_evidence("牛顿是谁", "短")
    assert evidence.refs[0]["url"] == "https://example.com/a"
    assert "摘要: 摘要句" in evidence.block


@pytest.mark.asyncio
async def test_fetch_page_excerpts_swallows_timeout():
    from lumina_core.search.evidence import fetch_page_excerpts

    def _slow(*args, **kwargs):
        raise TimeoutError("slow")

    with patch("lumina_core.search.evidence.fetch_article", side_effect=_slow):
        out = await fetch_page_excerpts(["https://example.com/hang"])
    assert out == []


def test_summarize_this_segment_is_sufficient():
    assert assess_evidence_sufficiency("总结本段", "x" * 500)
