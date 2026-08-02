"""Background book classification tasks."""

from __future__ import annotations

import logging
import sqlite3

from lumina_core.config import PromptsConfig

from lumina_core.classify.book import classify_book, normalize_category
from lumina_core.db.repos import BookRepo, SegmentRepo
from lumina_core.models.router import ProfileModelRouter

logger = logging.getLogger(__name__)


async def run_classify_book(
    conn: sqlite3.Connection,
    router: ProfileModelRouter,
    book_id: str,
    prompts: PromptsConfig | None = None,
) -> str | None:
    books_repo = BookRepo(conn)
    segments_repo = SegmentRepo(conn)
    book = books_repo.get(book_id)
    if not book:
        return None

    segments = segments_repo.list_for_book(book_id, include_body=True)
    sample = ""
    if segments:
        sample = (segments[0].get("raw_text") or "")[:2000]

    try:
        category = await classify_book(
            router,
            title=book.get("title") or "",
            author=book.get("author"),
            text_sample=sample,
            prompts=prompts,
        )
    except Exception:
        logger.exception("book classify failed for %s", book_id)
        return None

    books_repo.update(book_id, category=category)
    return category


def validate_manual_category(category: str | None) -> str | None:
    if category is None:
        return None
    return normalize_category(category)
