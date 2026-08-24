"""Background document ingest after fast library insert."""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Any, Callable, Coroutine

from lumina_core.chunker.document_map import heuristic_document_map, refine_document_map
from lumina_core.chunker.embeddings import build_boundary_scorer
from lumina_core.config import CHUNKER_VERSION, ModelsConfig, Settings, resolve_chunk_budget
from lumina_core.db.connection import detach_db_lock
from lumina_core.db.repos import BookRepo, SegmentRepo
from lumina_core.db.schema import connect_db
from lumina_core.ingest.loader import (
    author_from_metadata,
    build_segments,
    load_document,
    title_from_path,
)
from lumina_core.ingest.ocr import OcrProgressCallback
from lumina_core.ingest.progress import DocumentLoadCancelled
from lumina_core.search.fts import index_book
from lumina_core.translate.language import infer_language

logger = logging.getLogger(__name__)

EmitCallback = Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]
ScheduleClassify = Callable[[str], None]


def _load_ingest_sync(
    dest: Path,
    fmt: str,
    settings: Settings,
    on_progress: OcrProgressCallback | None,
    cancel_event: threading.Event,
) -> tuple[str, dict[str, Any]]:
    """CPU/IO heavy extract — runs off the asyncio event loop."""
    if cancel_event.is_set():
        raise DocumentLoadCancelled("已取消")
    text, metadata = load_document(
        dest,
        fmt,
        on_progress=on_progress,
        settings=settings,
        cancel_event=cancel_event,
    )
    if cancel_event.is_set():
        raise DocumentLoadCancelled("已取消")
    if not text.strip():
        raise RuntimeError("文档无可提取文本")
    return text, metadata


def _segment_ingest_sync(
    book_id: str,
    text: str,
    metadata: dict[str, Any],
    models: ModelsConfig,
    on_progress: OcrProgressCallback | None,
    cancel_event: threading.Event,
    document_map: list | None,
) -> list[dict[str, Any]]:
    if cancel_event.is_set():
        raise DocumentLoadCancelled("已取消")
    budget = resolve_chunk_budget(models)
    if on_progress:
        on_progress(0, 0, "正在按文档地图切分阅读单元…")
    scorer = build_boundary_scorer(cancelled=cancel_event.is_set)
    try:
        return build_segments(
            book_id,
            text,
            budget=budget,
            scorer=scorer,
            document_map=document_map,
            structure_roles=metadata.get("structure_roles"),
        )
    except InterruptedError as exc:
        raise DocumentLoadCancelled("已取消") from exc


def _persist_ingest_sync(
    db_path: Path,
    *,
    book_id: str,
    src: Path,
    metadata: dict[str, Any],
    detected_language: str | None,
    target_language: str,
    segments: list[dict[str, Any]],
    ingest_meta: dict[str, Any],
) -> None:
    """Persist through a dedicated WAL connection so library reads stay available."""
    conn = connect_db(db_path)
    try:
        books_repo = BookRepo(conn)
        if not books_repo.get(book_id):
            return
        SegmentRepo(conn).finalize_ingest(
            book_id,
            segments,
            title=title_from_path(src, metadata),
            author=author_from_metadata(metadata),
            language=detected_language,
            target_language=target_language,
            metadata_json=ingest_meta,
        )
        book_row = books_repo.get(book_id)
        if book_row:
            index_book(conn, book_row)
        SegmentRepo(conn).backfill_char_counts(book_id)
    finally:
        conn.close()
        detach_db_lock(conn)


async def run_ingest_job(
    *,
    book_id: str,
    dest: Path,
    fmt: str,
    src: Path,
    conn,
    db_path: Path,
    models: ModelsConfig,
    settings: Settings,
    target_language: str,
    job_queue,
    emit: EmitCallback,
    schedule_classify: ScheduleClassify,
    cancel_event: threading.Event | None = None,
) -> str:
    """Extract text, segment, prefetch summaries; emit SSE progress events."""
    loop = asyncio.get_running_loop()
    books_repo = BookRepo(conn)
    cancel_event = cancel_event or threading.Event()

    def on_progress(page: int, total: int, message: str) -> None:
        if cancel_event.is_set():
            return
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
        book = await asyncio.to_thread(books_repo.get, book_id)
        if not book or book.get("status") != "processing":
            return "cancelled"

        await emit(
            book_id,
            {
                "type": "ingest_progress",
                "page": 0,
                "total": 0,
                "message": "正在解析文档…",
            },
        )

        text, metadata = await asyncio.to_thread(
            _load_ingest_sync,
            dest,
            fmt,
            settings,
            on_progress,
            cancel_event,
        )
        if cancel_event.is_set():
            raise DocumentLoadCancelled("已取消")
        await emit(
            book_id,
            {
                "type": "ingest_progress",
                "page": 0,
                "total": 0,
                "message": "正在识别序言与正文结构…",
            },
        )
        units = heuristic_document_map(
            text, structure_roles=metadata.get("structure_roles")
        )
        router = getattr(job_queue, "router", None)
        prompts = getattr(job_queue, "prompts", None)
        units = await refine_document_map(
            units,
            router=router,
            prompts=prompts,
            cancel_event=cancel_event,
        )
        segments = await asyncio.to_thread(
            _segment_ingest_sync,
            book_id,
            text,
            metadata,
            models,
            on_progress,
            cancel_event,
            units,
        )

        ingest_meta = dict(metadata)
        ingest_meta["total_char_count"] = len(text.strip())
        ingest_meta["chunker_version"] = CHUNKER_VERSION
        ingest_meta["chunk_target_chars"] = resolve_chunk_budget(models).target_chars
        detected_language = infer_language(text)

        if cancel_event.is_set():
            raise DocumentLoadCancelled("已取消")

        await asyncio.to_thread(
            _persist_ingest_sync,
            db_path,
            book_id=book_id,
            src=src,
            metadata=metadata,
            detected_language=detected_language,
            target_language=target_language,
            segments=segments,
            ingest_meta=ingest_meta,
        )

        if job_queue.auto_start_summary:
            await job_queue.enqueue_book_prefetch(book_id)
        schedule_classify(book_id)

        await emit(
            book_id,
            {
                "type": "ingest_complete",
                "segment_count": len(segments),
            },
        )
        return "completed"
    except DocumentLoadCancelled:
        logger.info("Ingest cancelled for book %s", book_id)
        try:
            current = await asyncio.to_thread(books_repo.get, book_id)
            if current and current.get("status") == "processing":
                await asyncio.to_thread(
                    books_repo.update,
                    book_id,
                    status="error",
                    metadata_json={"ingest_error": "已取消导入"},
                )
        except Exception:
            logger.exception("Failed to mark cancelled book %s", book_id)
        await emit(
            book_id,
            {
                "type": "ingest_cancelled",
                "message": "已取消导入",
            },
        )
        return "cancelled"
    except Exception as exc:
        logger.exception("Ingest failed for book %s", book_id)
        message = str(exc)
        try:
            current = await asyncio.to_thread(books_repo.get, book_id)
            if current:
                await asyncio.to_thread(
                    books_repo.update,
                    book_id,
                    status="error",
                    metadata_json={"ingest_error": message},
                )
        except Exception:
            logger.exception("Failed to mark book %s as error", book_id)
        await emit(
            book_id,
            {
                "type": "ingest_failed",
                "message": message,
            },
        )
        return "failed"
