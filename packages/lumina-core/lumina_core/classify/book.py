"""LLM book category classification."""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel, field_validator

from lumina_core.models.router import ProfileModelRouter, parse_json_response

logger = logging.getLogger(__name__)

BOOK_CATEGORIES: tuple[str, ...] = ("文学", "历史", "科技", "哲学", "经济", "传记", "其他")
DEFAULT_CATEGORY = "其他"

CLASSIFY_PROMPT = """你是图书分类助手。根据书名、作者与正文样本，将书籍归入以下唯一主类之一：
{categories}

只输出 JSON，不要其他文字。示例：{{"category": "历史"}}

书名：{title}
作者：{author}
正文样本：
{text}
"""


class BookCategoryResult(BaseModel):
    category: str

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        return normalize_category(value)


def normalize_category(value: str | None) -> str:
    if not value:
        return DEFAULT_CATEGORY
    cleaned = value.strip()
    if cleaned in BOOK_CATEGORIES:
        return cleaned
    return DEFAULT_CATEGORY


async def classify_book(
    router: ProfileModelRouter,
    *,
    title: str,
    author: str | None,
    text_sample: str,
) -> str:
    prompt = CLASSIFY_PROMPT.format(
        categories=" · ".join(BOOK_CATEGORIES),
        title=title or "未知",
        author=author or "未知",
        text=(text_sample or "")[:2000],
    )
    raw = await router.complete(prompt, profile="summarize", json_mode=True)
    try:
        data = parse_json_response(raw) if isinstance(raw, str) else raw
        return BookCategoryResult.model_validate(data).category
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("invalid classify response: %s", exc)
        return DEFAULT_CATEGORY
