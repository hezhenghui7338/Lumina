"""Background document ingest after fast library insert."""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Any, Callable, Coroutine

from lumina_core.chunker.chunker import chunk_text, rebuild_chunks
from lumina_core.chunker.coop import GilYielder, coerce_char_progress
from lumina_core.chunker.document_map import heuristic_document_map, refine_document_map
from lumina_core.chunker.embeddings import build_boundary_scorer
from lumina_core.chunker.llm_cuts import refine_spans_with_llm
from lumina_core.chunker.tree import build_document_tree
from lumina_core.config import (
    CHUNKER_VERSION,
    ModelsConfig,
    Settings,
    normalize_segment_tier,
    resolve_chunk_budget,
)
from lumina_core.db.connection import detach_db_lock
from lumina_core.db.repos import BookRepo, SegmentRepo, resolve_ingest_title
from lumina_core.db.schema import connect_db
from lumina_core.ingest.loader import (
    author_from_metadata,
    build_segments,
    load_document,
    title_from_path,
)
from lumina_core.ingest.ocr import OcrProgressCallback
from lumina_core.ingest.progress import DocumentLoadCancelled
from lumina_core.jobs.cpu_worker import (
    models_for_cpu_job,
    run_cpu_worker_sync,
    settings_for_cpu_job,
    should_offload_cpu,
)
from lumina_core.search.fts import index_book
from lumina_core.translate.language import infer_language

logger = logging.getLogger(__name__)

EmitCallback = Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]
ScheduleClassify = Callable[[str], None]


def slim_book_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Drop the unused document_tree blob so GET /books stays small."""
    from lumina_core.ingest.cover import strip_cover_payload

    out = strip_cover_payload(dict(metadata))
    out.pop("document_tree", None)
    # Illustration hits are persisted to book_assets; never store blobs in metadata.
    out.pop("illustrations", None)
    return out


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


def _map_ingest_sync(
    text: str,
    metadata: dict[str, Any],
    cancel_event: threading.Event,
    on_progress: Callable[..., None] | None = None,
):
    if cancel_event.is_set():
        raise DocumentLoadCancelled("已取消")
    return heuristic_document_map(
        text,
        structure_roles=metadata.get("structure_roles"),
        yielder=GilYielder(
            cancel_event,
            on_progress=coerce_char_progress(on_progress),
            progress_total=len(text),
            progress_message="正在识别序言与正文结构…",
        ),
    )


def _chunk_ingest_sync(
    text: str,
    metadata: dict[str, Any],
    models: ModelsConfig,
    cancel_event: threading.Event,
    document_map: list | None,
    on_progress=None,
):
    if cancel_event.is_set():
        raise DocumentLoadCancelled("已取消")
    budget = resolve_chunk_budget(models)
    scorer = build_boundary_scorer(cancelled=cancel_event.is_set)
    try:
        tree = build_document_tree(
            text,
            structure_roles=metadata.get("structure_roles"),
            yielder=GilYielder(
                cancel_event,
                on_progress=coerce_char_progress(on_progress),
                progress_total=len(text),
                progress_message="正在识别结构树…",
            ),
        )
        chunks = chunk_text(
            text,
            budget=budget,
            scorer=scorer,
            document_map=document_map,
            structure_roles=metadata.get("structure_roles"),
            document_tree=tree,
            cancel_event=cancel_event,
            on_progress=on_progress,
        )
        return chunks, tree, budget
    except InterruptedError as exc:
        raise DocumentLoadCancelled("已取消") from exc


def _payload_ingest_sync(
    book_id: str,
    text: str,
    chunks,
    metadata: dict[str, Any],
    budget,
    segment_tier: str,
    cancel_event: threading.Event,
) -> tuple[list[dict[str, Any]], dict[str, Any], str | None]:
    if cancel_event.is_set():
        raise DocumentLoadCancelled("已取消")
    segments = build_segments(book_id, text, chunks=chunks)
    ingest_meta = slim_book_metadata(metadata)
    ingest_meta["total_char_count"] = len(text.strip())
    ingest_meta["chunker_version"] = CHUNKER_VERSION
    ingest_meta["chunk_target_chars"] = budget.target_chars
    ingest_meta["segment_tier"] = segment_tier
    return segments, ingest_meta, infer_language(text)


def _rebuild_chunks_sync(
    text: str,
    spans: list[tuple[int, int]],
    metadata: dict[str, Any],
    tree,
    cancel_event: threading.Event,
):
    if cancel_event.is_set():
        raise DocumentLoadCancelled("已取消")
    return rebuild_chunks(
        text,
        spans,
        structure_roles=metadata.get("structure_roles"),
        document_tree=tree,
    )


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
    chunks: list | None = None,
) -> None:
    """Persist through a dedicated WAL connection so library reads stay available."""
    conn = connect_db(db_path)
    try:
        books_repo = BookRepo(conn)
        book = books_repo.get(book_id)
        if not book:
            return
        persist_meta = slim_book_metadata(ingest_meta)
        title = resolve_ingest_title(book, title_from_path(src, metadata), persist_meta)
        SegmentRepo(conn).finalize_ingest(
            book_id,
            segments,
            title=title,
            author=author_from_metadata(metadata),
            language=detected_language,
            target_language=target_language,
            metadata_json=persist_meta,
        )
        _persist_cover_if_any(
            books_repo,
            book_id,
            library_file=Path(str(book["file_path"])),
            fmt=str(book.get("format") or ""),
        )
        _persist_illustrations_if_any(
            conn,
            book_id=book_id,
            library_file=Path(str(book["file_path"])),
            fmt=str(book.get("format") or ""),
            metadata=metadata,
            segments=segments,
            chunks=chunks,
        )
        book_row = books_repo.get(book_id)
        if book_row:
            index_book(conn, book_row)
        SegmentRepo(conn).backfill_char_counts(book_id)
    finally:
        conn.close()
        detach_db_lock(conn)


def _persist_cover_if_any(
    books_repo: BookRepo,
    book_id: str,
    *,
    library_file: Path,
    fmt: str,
) -> None:
    """Best-effort cover extract after segments land; never fail ingest."""
    if not fmt or fmt == "txt":
        return
    try:
        from lumina_core.ingest.cover import save_book_cover

        rel = save_book_cover(library_file, library_file.parent, fmt)
        if rel:
            books_repo.update(book_id, cover_path=rel)
    except Exception:
        logging.getLogger(__name__).debug(
            "cover extract skipped for %s", book_id, exc_info=True
        )


def _persist_illustrations_if_any(
    conn,
    *,
    book_id: str,
    library_file: Path,
    fmt: str,
    metadata: dict[str, Any],
    segments: list[dict[str, Any]],
    chunks: list | None,
) -> None:
    """Best-effort EPUB illustration index; never fail ingest."""
    fmt_l = (fmt or "").lower()
    if fmt_l not in {"epub", "mobi", "azw", "azw3"}:
        return
    status = metadata.get("illustrations_status")
    if status == "skipped_ocr":
        try:
            BookRepo(conn).update(book_id, illustrations_status="skipped_ocr")
        except Exception:
            pass
        return
    hits = list(metadata.get("illustrations") or [])
    if not hits:
        try:
            BookRepo(conn).update(book_id, illustrations_status="none")
        except Exception:
            pass
        return
    epub_path = library_file
    if fmt_l != "epub":
        sibling = library_file.with_suffix(".epub")
        if sibling.is_file():
            epub_path = sibling
        else:
            try:
                BookRepo(conn).update(book_id, illustrations_status="none")
            except Exception:
                pass
            return
    try:
        from lumina_core.ingest.illustrations import (
            map_illustrations_to_chunks,
            persist_epub_illustrations,
        )

        if chunks:
            mapped = map_illustrations_to_chunks(hits, chunks)
        else:
            from lumina_core.ingest.illustrations import (
                map_illustrations_to_joined_segments,
            )

            mapped = map_illustrations_to_joined_segments(
                hits,
                extracted_text="".join(str(s.get("raw_text") or "") for s in segments),
                segments=segments,
            )
        cover = None
        book_row = BookRepo(conn).get(book_id)
        if book_row:
            cover = book_row.get("cover_path")
        persist_epub_illustrations(
            conn,
            book_id=book_id,
            epub_path=epub_path,
            book_dir=library_file.parent,
            mapped=mapped,
            cover_path=str(cover) if cover else None,
            segments_by_idx={int(s["idx"]): s for s in segments},
        )
    except Exception:
        logging.getLogger(__name__).debug(
            "illustration persist skipped for %s", book_id, exc_info=True
        )
        try:
            BookRepo(conn).update(book_id, illustrations_status="error")
        except Exception:
            pass


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

        if should_offload_cpu(dest):
            result = await asyncio.to_thread(
                run_cpu_worker_sync,
                {
                    "kind": "ingest",
                    "book_id": book_id,
                    "dest": str(dest),
                    "fmt": fmt,
                    "src": str(src),
                    "db_path": str(db_path),
                    "target_language": target_language,
                    "segment_tier": normalize_segment_tier(
                        getattr(settings, "default_segment_tier", "normal")
                    ),
                    "settings": settings_for_cpu_job(settings),
                    "_ocr_cloud_api_key": settings.ocr_cloud_api_key,
                    "models": models_for_cpu_job(models),
                },
                cancel_event,
                on_progress,
                Path(settings.data_dir),
            )
            if job_queue.auto_start_summary:
                await job_queue.enqueue_book_prefetch(book_id)
            schedule_classify(book_id)
            await emit(
                book_id,
                {
                    "type": "ingest_complete",
                    "segment_count": int(result.get("segment_count") or 0),
                },
            )
            return "completed"

        if fmt == "txt":
            from lumina_core.ingest.txt_persist import persist_streamed_txt_ingest

            count, _ingest_meta, _lang = await asyncio.to_thread(
                persist_streamed_txt_ingest,
                db_path,
                book_id=book_id,
                dest=dest,
                src=src,
                models=models,
                metadata={},
                target_language=target_language,
                segment_tier=normalize_segment_tier(
                    getattr(settings, "default_segment_tier", "normal")
                ),
                cancel_event=cancel_event,
                on_progress=on_progress,
            )
            if job_queue.auto_start_summary:
                await job_queue.enqueue_book_prefetch(book_id)
            schedule_classify(book_id)
            await emit(
                book_id,
                {
                    "type": "ingest_complete",
                    "segment_count": int(count),
                },
            )
            return "completed"

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
        units = await asyncio.to_thread(
            _map_ingest_sync,
            text,
            metadata,
            cancel_event,
            on_progress,
        )
        router = getattr(job_queue, "router", None)
        prompts = getattr(job_queue, "prompts", None)
        units = await refine_document_map(
            units,
            router=router,
            prompts=prompts,
            cancel_event=cancel_event,
        )
        await emit(
            book_id,
            {
                "type": "ingest_progress",
                "page": 0,
                "total": 0,
                "message": "正在按文档地图切分阅读单元…",
            },
        )
        chunks, tree, budget = await asyncio.to_thread(
            _chunk_ingest_sync,
            text,
            metadata,
            models,
            cancel_event,
            units,
            on_progress,
        )
        segment_tier = normalize_segment_tier(
            getattr(settings, "default_segment_tier", "normal")
        )
        if segment_tier == "advanced":
            await emit(
                book_id,
                {
                    "type": "ingest_progress",
                    "page": 0,
                    "total": 0,
                    "message": "正在用高级分段校准超长块…",
                },
            )
            spans = await refine_spans_with_llm(
                text,
                [(chunk.start_offset, chunk.end_offset) for chunk in chunks],
                max_chars=budget.max_chars,
                min_chars=budget.min_chars,
                router=router,
                prompts=prompts,
                cancel_event=cancel_event,
            )
            chunks = await asyncio.to_thread(
                _rebuild_chunks_sync,
                text,
                spans,
                metadata,
                tree,
                cancel_event,
            )
        segments, ingest_meta, detected_language = await asyncio.to_thread(
            _payload_ingest_sync,
            book_id,
            text,
            chunks,
            metadata,
            budget,
            segment_tier,
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
                "message": "正在写入书库…",
            },
        )
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
            chunks=chunks,
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
