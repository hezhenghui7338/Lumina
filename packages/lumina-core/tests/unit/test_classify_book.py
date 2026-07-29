"""Book classification tests."""

from __future__ import annotations

import pytest

from lumina_core.classify.book import (
    BOOK_CATEGORIES,
    classify_book,
    normalize_category,
)
from tests.support.mock_router import MockModelRouter


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("历史", "历史"),
        (" 科技 ", "科技"),
        ("未知类", "其他"),
        ("", "其他"),
        (None, "其他"),
    ],
)
def test_normalize_category(raw, expected):
    assert normalize_category(raw) == expected


@pytest.mark.asyncio
async def test_classify_book_valid_response():
    router = MockModelRouter(responses={"summarize": {"category": "哲学"}})
    category = await classify_book(
        router,
        title="沉思录",
        author="马可·奥勒留",
        text_sample="关于人生与德性的思考……",
    )
    assert category == "哲学"


@pytest.mark.asyncio
async def test_classify_book_invalid_falls_back_to_other():
    router = MockModelRouter(responses={"summarize": {"category": "科幻"}})
    category = await classify_book(
        router,
        title="三体",
        author="刘慈欣",
        text_sample="宇宙社会学……",
    )
    assert category == "其他"


def test_categories_cover_expected_set():
    assert "文学" in BOOK_CATEGORIES
    assert "其他" in BOOK_CATEGORIES
    assert len(BOOK_CATEGORIES) == 7
