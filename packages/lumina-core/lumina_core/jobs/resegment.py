"""Background whole-book resegmentation."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import Any

from lumina_core.chunker.document_map import heuristic_document_map, refine_document_map
from lumina_core.chunker.embeddings import build_boundary_scorer
from lumina_core.config import CHUNKER_VERSION, Settings, resolve_chunk_budget
from lumina_core.db.connection import detach_db_lock
from lumina_core.db.repos import BookRepo, SegmentRepo
from lumina_core.db.schema import connect_db
from lumina_core.ingest.loader import build_segments, load_document
from lumina_core.ingest.progress import DocumentLoadCancelled
from lumina_core.ingest.ocr import OcrProgressCallback
from lumina_core.jobs.ingest import EmitCallback

logger = logging.getLogger(__name__)


class ResegmentCancelled(RuntimeError):
    pass


def _extract_document_sync(
    file_path: Path,
    fmt: str,
    settings: Settings,
    on_progress: OcrProgressCallback | None,
    cancel_event: threading.Event,
) -> tuple[str, dict[str, Any]]:
    if cancel_event.is_set():
        raise ResegmentCancelled
    try:
        text, metadata = load_document(
            file_path,
            fmt,
            on_progress=on_progress,
            settings=settings,
            cancel_event=cancel_event,
        )
    except DocumentLoadCancelled as exc:
        raise ResegmentCancelled from exc
    if cancel_event.is_set():
        raise ResegmentCancelled
    if not text.strip():
        raise RuntimeError("文档无可提取文本")
    return text, metadata


def _segment_resegment_sync(
    book_id: str,
    text: str,
    metadata: dict[str, Any],
    chunk_target_chars: int,
    on_progress: OcrProgressCallback | None,
    cancel_event: threading.Event,
    document_map: list | None,
) -> list[dict[str, Any]]:
    if cancel_event.is_set():
        raise ResegmentCancelled
    budget = resolve_chunk_budget(target_chars=chunk_target_chars)
    if on_progress:
        on_progress(0, 0, "正在按文档地图切分阅读单元…")
    try:
        segments = build_segments(
            book_id,
            text,
            budget=budget,
            scorer=build_boundary_scorer(cancelled=cancel_event.is_set),
            document_map=document_map,
            structure_roles=metadata.get("structure_roles"),
        )
    except InterruptedError as exc:
        raise ResegmentCancelled from exc
    if cancel_event.is_set():
        raise ResegmentCancelled
    return segments


def _metadata_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value:
        try:
            decoded = json.loads(value)
            return dict(decoded) if isinstance(decoded, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _update_book_sync(
    db_path: Path,
    book_id: str,
    *,
    status: str,
    metadata_json: dict[str, Any],
) -> None:
    conn = connect_db(db_path)
    try:
        BookRepo(conn).update(
            book_id,
            status=status,
            metadata_json=metadata_json,
        )
    finally:
        conn.close()
        detach_db_lock(conn)


def _persist_resegment_sync(
    db_path: Path,
    book_id: str,
    segments: list[dict[str, Any]],
    *,
    metadata_json: dict[str, Any],
    status: str,
) -> None:
    """Atomically replace segments through a dedicated WAL connection."""
    conn = connect_db(db_path)
    try:
        SegmentRepo(conn).replace_for_book(
            book_id,
            segments,
            metadata_json=metadata_json,
            status=status,
        )
    finally:
        conn.close()
        detach_db_lock(conn)


async def run_resegment_job(
    *,
    book_id: str,
    chunk_target_chars: int,
    previous_status: str,
    conn,
    db_path: Path,
    settings: Settings,
    job_queue,
    emit: EmitCallback,
    cancel_event: threading.Event,
) -> str:
    """Re-extract and atomically replace all segment-bound data off the event loop."""
    books_repo = BookRepo(conn)
    old_status = previous_status
    old_metadata: dict[str, Any] = {}
    was_paused = False
    had_book_work = False
    loop = asyncio.get_running_loop()

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
        old_metadata = _metadata_dict(book.get("metadata_json"))

        await emit(
            book_id,
            {
                "type": "resegment_started",
                "chunk_target_chars": chunk_target_chars,
            },
        )
        had_book_work = job_queue.has_book_work(book_id)
        was_paused = await job_queue.prepare_book_resegment(book_id)
        if cancel_event.is_set():
            raise ResegmentCancelled

        text, extracted_metadata = await asyncio.to_thread(
            _extract_document_sync,
            Path(str(book["file_path"])),
            str(book["format"]),
            settings,
            on_progress,
            cancel_event,
        )
        if cancel_event.is_set():
            raise ResegmentCancelled
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
            text, structure_roles=extracted_metadata.get("structure_roles")
        )
        units = await refine_document_map(
            units,
            router=getattr(job_queue, "router", None),
            prompts=getattr(job_queue, "prompts", None),
            cancel_event=cancel_event,
        )
        segments = await asyncio.to_thread(
            _segment_resegment_sync,
            book_id,
            text,
            extracted_metadata,
            chunk_target_chars,
            on_progress,
            cancel_event,
            units,
        )

        metadata = old_metadata | extracted_metadata
        metadata["total_char_count"] = len(text.strip())
        metadata["chunker_version"] = CHUNKER_VERSION
        metadata["chunk_target_chars"] = chunk_target_chars
        metadata.pop("resegment_error", None)
        final_status = old_status if old_status in {"unread", "reading"} else "reading"

        # Cancellation is accepted up to this commit boundary. Once the atomic
        # replacement starts, it is allowed to finish to avoid a false
        # "cancelled" result after new segments have already been committed.
        if cancel_event.is_set():
            raise ResegmentCancelled
        job_queue.discard_book_suspended(book_id)
        await asyncio.to_thread(
            _persist_resegment_sync,
            db_path,
            book_id,
            segments,
            metadata_json=metadata,
            status=final_status,
        )

        if not was_paused:
            job_queue.unpause_book(book_id)
        if job_queue.auto_start_summary and not was_paused:
            await job_queue.enqueue_book_prefetch(book_id)

        await emit(
            book_id,
            {
                "type": "ingest_complete",
                "segment_count": len(segments),
                "resegmented": True,
                "chunk_target_chars": chunk_target_chars,
            },
        )
        return "completed"
    except ResegmentCancelled:
        try:
            await asyncio.to_thread(
                _update_book_sync,
                db_path,
                book_id,
                status=old_status,
                metadata_json=old_metadata,
            )
            if not was_paused:
                if had_book_work:
                    await job_queue.start_book(book_id)
                else:
                    job_queue.unpause_book(book_id)
        except Exception:
            logger.exception("Failed to restore book %s after cancellation", book_id)
        await emit(
            book_id,
            {
                "type": "resegment_cancelled",
                "message": "已取消重新分段",
                "status": old_status,
            },
        )
        return "cancelled"
    except Exception as exc:
        logger.exception("Resegment failed for book %s", book_id)
        message = str(exc)
        try:
            failure_metadata = old_metadata | {"resegment_error": message}
            await asyncio.to_thread(
                _update_book_sync,
                db_path,
                book_id,
                status=old_status,
                metadata_json=failure_metadata,
            )
            if not was_paused:
                if had_book_work:
                    await job_queue.start_book(book_id)
                else:
                    job_queue.unpause_book(book_id)
        except Exception:
            logger.exception("Failed to restore book %s after resegment error", book_id)
        await emit(
            book_id,
            {
                "type": "resegment_failed",
                "message": f"重新分段失败：{message}",
                "status": old_status,
            },
        )
        return "failed"
