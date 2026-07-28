"""Web search tests."""

import pytest

from lumina_core.search.web import (
    assess_evidence_sufficiency,
    classify_domain,
    search_web,
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


@pytest.mark.asyncio
async def test_search_web_returns_list():
    results = await search_web("Python programming")
    assert isinstance(results, list)
