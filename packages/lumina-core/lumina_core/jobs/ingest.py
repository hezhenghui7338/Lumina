"""Background document ingest after fast library insert."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable, Coroutine

from lumina_core.config import CHUNKER_VERSION, ModelsConfig, resolve_chunk_budget
from lumina_core.db.repos import BookRepo, SegmentRepo
from lumina_core.ingest.loader import (
    author_from_metadata,
    build_segments,
    load_document,
    title_from_path,
)
from lumina_core.ingest.ocr import OcrProgressCallback
from lumina_core.search.fts import index_book
from lumina_core.translate.language import infer_language

logger = logging.getLogger(__name__)

EmitCallback = Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]
ScheduleClassify = Callable[[str], None]


def _finish_ingest_sync(
    book_id: str,
    dest: Path,
    fmt: str,
    src: Path,
    models: ModelsConfig,
    on_progress: OcrProgressCallback | None,
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    """CPU/IO heavy extract + chunk — runs off the asyncio event loop."""
    text, metadata = load_document(dest, fmt, on_progress=on_progress)
    if not text.strip():
        raise RuntimeError("文档无可提取文本")
    budget = resolve_chunk_budget(models)
    segments = build_segments(book_id, text, budget=budget)
    return text, metadata, segments


async def run_ingest_job(
    *,
    book_id: str,
    dest: Path,
    fmt: str,
    src: Path,
    conn,
    models: ModelsConfig,
    target_language: str,
    job_queue,
    emit: EmitCallback,
    schedule_classify: ScheduleClassify,
) -> None:
    """Extract text, segment, prefetch summaries; emit SSE progress events."""
    loop = asyncio.get_running_loop()
    books_repo = BookRepo(conn)

    def on_progress(page: int, total: int, message: str) -> None:
        asyncio.run_coroutine_threadsafe(
            emit(
                book_id,
                {
                    "type": "ingest_progress",
                    "page": page,
                    "total": total,
                    "message": message,
                },
            ),
            loop,
        )

    try:
        book = books_repo.get(book_id)
        if not book or book.get("status") != "processing":
            return

        text, metadata, segments = await asyncio.to_thread(
            _finish_ingest_sync,
            book_id,
            dest,
            fmt,
            src,
            models,
            on_progress,
        )

        ingest_meta = dict(metadata)
        ingest_meta["total_char_count"] = len(text.strip())
        ingest_meta["chunker_version"] = CHUNKER_VERSION
        detected_language = infer_language(text)

        books_repo.update(
            book_id,
            title=title_from_path(src, metadata),
            author=author_from_metadata(metadata),
            language=detected_language,
            target_language=target_language,
            segment_count=len(segments),
            status="unread",
            metadata_json=ingest_meta,
        )
        SegmentRepo(conn).insert_many(segments)
        book_row = books_repo.get(book_id)
        if book_row:
            index_book(conn, book_row)

        await job_queue.enqueue_book_prefetch(book_id)
        schedule_classify(book_id)

        await emit(
            book_id,
            {
                "type": "ingest_complete",
                "segment_count": len(segments),
            },
        )
    except Exception as exc:
        logger.exception("Ingest failed for book %s", book_id)
        message = str(exc)
        try:
            books_repo.update(book_id, status="error", metadata_json={"ingest_error": message})
        except Exception:
            logger.exception("Failed to mark book %s as error", book_id)
        await emit(
            book_id,
            {
                "type": "ingest_failed",
                "message": message,
            },
        )
