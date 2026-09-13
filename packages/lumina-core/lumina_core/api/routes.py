"""FastAPI routes."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sqlite3
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from lumina_core.app_state import AppState, default_rss_sources
from lumina_core.config import RESEGMENT_MAX_TARGET_CHARS, RESEGMENT_MIN_TARGET_CHARS
from lumina_core.models.context_probe import (
    ContextProbeStatus,
    idle_probe_status,
    run_context_probe,
)
from lumina_core.chat.news_service import chat_with_article, stream_chat_with_article
from lumina_core.chat.service import chat_with_book, stream_chat_with_book
from lumina_core.chunker.boundary import (
    BoundaryError,
    apply_cut,
    list_cut_offsets,
    segment_anchor_label,
)
from lumina_core.config import (
    CHUNK_MAX_CHARS,
    CHUNKER_VERSION,
    CORE_VERSION,
    ModelsConfig,
    PromptsConfig,
    Settings,
    normalize_segment_tier,
)
from lumina_core.classify.book import BOOK_CATEGORIES
from lumina_core.classify.tasks import run_classify_book, validate_manual_category
from lumina_core.db.repos import (
    CATALOG_PAGE_DEFAULT,
    CATALOG_WINDOW_DEFAULT,
    BookRepo,
    ChatRepo,
    NewsChatRepo,
    NoteRepo,
    SegmentRepo,
    metadata_with_title_user_set,
)
from lumina_core.export.markdown import content_disposition_attachment, export_book_markdown
from lumina_core.ingest.loader import (
    copy_to_library,
    detect_format,
    file_hash,
    title_from_path,
    validate_import,
)
from lumina_core.jobs.ingest import run_ingest_job
from lumina_core.jobs.resegment import run_resegment_job
from lumina_core.news.brief import build_brief
from lumina_core.news.read import load_cached_body, read_article
from lumina_core.news.store import NewsSourceRepo, NewsStore
from lumina_core.news.sync import sync_all
from lumina_core.search.fts import index_book, index_note, index_segment, search
from lumina_core.search.original import search_original
from lumina_core.tts.script import LISTEN_MODES, ListenMode
from lumina_core.tts.service import load_listen_script
from lumina_core.resource_probe import probe_ocr, probe_resource
from lumina_core.ops.helpers import (
    book_title,
    register_article_task,
    register_book_task,
    track_async_task,
    track_stream_events,
)
from lumina_core.secrets_store import persist_secrets
from lumina_core.settings_store import (
    load_prompts,
    merge_incoming_models,
    merge_ocr_cloud_api_key,
    merge_prompts,
    merge_tavily_api_key,
    models_to_dict,
    normalize_web_search_provider,
    save_models,
    save_settings,
    settings_public_dict,
)

router = APIRouter()
logger = logging.getLogger(__name__)

SUPPORTED_FORMATS = {
    "txt",
    "pdf",
    "epub",
    "mobi",
    "html",
    "rtf",
    "docx",
    "odt",
    "fb2",
}


class ImportRequest(BaseModel):
    paths: list[str]
    overwrite: bool = False


class ChatRequest(BaseModel):
    message: str
    segment_index: int = 0
    stream: bool = False
    quote: str | None = None
    scope: Literal["segment", "book"] = "segment"


class NewsChatRequest(BaseModel):
    message: str
    stream: bool = False
    quote: str | None = None


class ExportRequest(BaseModel):
    include_notes: bool = False
    mode: Literal["full", "sentences"] = "full"


class RetrySegmentsRequest(BaseModel):
    indices: list[int]
    summary_tier: Literal["normal", "advanced"] | None = None


class ResegmentRequest(BaseModel):
    chunk_target_chars: int = Field(
        ge=RESEGMENT_MIN_TARGET_CHARS,
        le=RESEGMENT_MAX_TARGET_CHARS,
    )
    segment_tier: Literal["normal", "advanced"] = "normal"


class SummarizeBatchRequest(BaseModel):
    book_ids: list[str] = []
    summary_tier: Literal["normal", "advanced"] = "normal"


class SummaryTierRequest(BaseModel):
    summary_tier: Literal["normal", "advanced"] = "normal"


class ReadingProgressUpdate(BaseModel):
    segment_index: int


class MoveBoundaryRequest(BaseModel):
    left_char_count: int = Field(ge=1)


class BookPatchUpdate(BaseModel):
    is_favorite: bool | None = None
    category: str | None = None
    title: str | None = None


class ContextProbeRequest(BaseModel):
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None


class SettingsUpdate(BaseModel):
    target_language: str | None = None
    web_search_provider: str | None = None
    web_search_enabled: bool | None = None
    tavily_api_key: str | None = None
    ocr_cloud_base_url: str | None = None
    ocr_cloud_model: str | None = None
    ocr_cloud_api_key: str | None = None
    ocr_cloud_timeout_seconds: float | None = Field(default=None, ge=1.0, le=300.0)
    debug_mode: bool | None = None
    auto_start_summary: bool | None = None
    default_segment_tier: Literal["normal", "advanced"] | None = None
    models: ModelsConfig | None = None
    prompts: PromptsConfig | None = None


class NoteCreate(BaseModel):
    book_id: str
    content: str
    segment_id: str
    quote: str | None = None
    type: str = "manual"


class NewsSourceCreate(BaseModel):
    url: str
    title: str = ""


def _state(request: Request) -> AppState:
    return request.app.state.lumina  # type: ignore[attr-defined]


def _prompts(state: AppState) -> PromptsConfig:
    if state.settings.prompts is not None:
        return state.settings.prompts
    return load_prompts(state.settings.data_dir)


_SCHEMA_STALE_DETAIL = "数据库 schema 过期，请重启应用"


def _raise_on_db_schema_error(exc: BaseException) -> None:
    if isinstance(exc, sqlite3.OperationalError):
        raise HTTPException(503, _SCHEMA_STALE_DETAIL) from exc
    raise exc


async def _purge_book(state: AppState, book_id: str) -> None:
    ingest_cancel = state.ingest_cancel_events.get(book_id)
    if ingest_cancel:
        ingest_cancel.set()
    resegment_cancel = state.resegment_cancel_events.get(book_id)
    if resegment_cancel:
        resegment_cancel.set()
    await state.job_queue.stop_book(book_id)
    BookRepo(state.conn).delete(book_id)
    book_dir = state.books_dir / book_id
    if book_dir.exists():
        await asyncio.to_thread(shutil.rmtree, book_dir)


def _processing_kind(state: AppState, book_id: str) -> str | None:
    if book_id in state.resegment_tasks:
        return "resegment"
    if book_id in state.ingest_tasks:
        return "ingest"
    return None


def _wire_job_events(state: AppState) -> None:
    async def _on_event(bid: str, payload: dict[str, Any]) -> None:
        for q in state.event_subscribers.get(bid, []):
            await q.put(payload)

    state.job_queue.set_event_callback(_on_event)


async def _queue_segment_retry(
    state: AppState,
    book_id: str,
    idx: int,
    *,
    seg: dict[str, Any] | None = None,
    summary_tier: str | None = None,
) -> None:
    if seg is None:
        seg = await asyncio.to_thread(
            SegmentRepo(state.conn).get_by_index, book_id, idx
        )
        if not seg:
            raise HTTPException(404, "Segment not found")
    await state.job_queue.unpause_book_async(book_id)
    await asyncio.to_thread(
        SegmentRepo(state.conn).set_status,
        seg["id"],
        "pending",
        retry_count=0,
    )
    await state.job_queue.enqueue_summarize(
        book_id,
        seg["id"],
        idx,
        high=True,
        summary_tier=summary_tier or seg.get("summary_tier") or "normal",
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _prioritize_summarize_activity(books: list[dict[str, Any]]) -> list[dict[str, Any]]:
    running: list[dict[str, Any]] = []
    queued: list[dict[str, Any]] = []
    rest: list[dict[str, Any]] = []
    for book in books:
        state = book.get("summarize_state")
        if state == "running":
            running.append(book)
        elif state == "queued":
            queued.append(book)
        else:
            rest.append(book)
    return running + queued + rest


def apply_book_list_filter(
    books: list[dict[str, Any]], filter_name: str
) -> list[dict[str, Any]]:
    """Queue-derived filters that cannot be expressed in SQL (summarize_state)."""
    if filter_name == "error":
        return [book for book in books if book.get("status") == "error"]
    if filter_name == "summarizing":
        return [
            book
            for book in books
            if book.get("status") != "error"
            and not _book_is_segmenting(book)
            and book.get("summarize_state") in ("running", "queued")
        ]
    if filter_name == "idle":
        return [
            book
            for book in books
            if book.get("status") != "error"
            and not _book_is_segmenting(book)
            and book.get("summarize_state") in ("idle", "paused")
        ]
    if filter_name == "segmenting":
        return [book for book in books if _book_is_segmenting(book)]
    return books


def _book_is_segmenting(book: dict[str, Any]) -> bool:
    if book.get("status") == "error":
        return False
    if book.get("status") == "processing" or book.get("summarize_state") == "segmenting":
        return True
    if book.get("summarize_state") in ("idle", "paused", "running", "queued"):
        return False
    if "summary_total_count" not in book and "segment_count" not in book:
        return False
    total = int(book.get("summary_total_count") or book.get("segment_count") or 0)
    return total <= 0


def book_public_dict(
    row: dict[str, Any],
    *,
    conn: sqlite3.Connection | None = None,
    summarize_active: dict[str, Any] | None = None,
    summarize_state: str | None = None,
    summarize_queued_count: int | None = None,
    summary_tier: str | None = None,
    processing_kind: str | None = None,
) -> dict[str, Any]:
    """Normalize book row for JSON (SQLite stores is_favorite as INTEGER)."""
    out = dict(row)
    if "is_favorite" in out and out["is_favorite"] is not None:
        out["is_favorite"] = bool(out["is_favorite"])

    meta: dict[str, Any] = {}
    if out.get("metadata_json"):
        try:
            meta = json.loads(out["metadata_json"]) if isinstance(out["metadata_json"], str) else out["metadata_json"]
        except (json.JSONDecodeError, TypeError):
            meta = {}
    out["total_char_count"] = meta.get("total_char_count")
    out["chunker_version"] = meta.get("chunker_version")
    out["chunk_target_chars"] = meta.get("chunk_target_chars")
    ingest_error = meta.get("ingest_error")
    out["ingest_error"] = (
        ingest_error.strip() if isinstance(ingest_error, str) and ingest_error.strip() else None
    )
    out["processing_kind"] = processing_kind
    out.setdefault("index_status", out.get("index_status") or "idle")

    if conn is not None and out.get("id"):
        progress = BookRepo(conn).summary_progress(out["id"])
        out.update(progress)
    else:
        out.setdefault("summary_ready_count", 0)
        out.setdefault("summary_total_count", out.get("segment_count") or 0)

    if summarize_active is not None:
        out["summarize_active"] = summarize_active

    total = int(out.get("summary_total_count") or 0)
    if row.get("status") == "processing" or (
        row.get("status") != "error" and total <= 0
    ):
        out["summarize_state"] = "segmenting"
        out["summarize_queued_count"] = 0
        out["summary_tier"] = summary_tier or "normal"
    elif summarize_state is not None:
        out["summarize_state"] = summarize_state
        out["summarize_queued_count"] = summarize_queued_count or 0
        out["summary_tier"] = summary_tier or "normal"

    out.pop("metadata_json", None)
    return out


def _book_public_with_queue(state: AppState, row: dict[str, Any]) -> dict[str, Any]:
    book_id = row.get("id")
    if not book_id:
        return book_public_dict(row, conn=state.conn)
    progress = BookRepo(state.conn).summary_progress(book_id)
    ready = int(progress["summary_ready_count"])
    total = int(progress["summary_total_count"])
    return book_public_dict(
        row,
        conn=state.conn,
        summarize_active=state.job_queue.summarize_active_for_book(book_id),
        summarize_state=state.job_queue.summarize_state_for_book(
            book_id, ready=ready, total=total
        ),
        summarize_queued_count=state.job_queue._summarize_queued_count_for_book(
            book_id
        ),
        summary_tier=state.job_queue.summary_tier_for_book(book_id),
    )


async def _emit_book_event(state: AppState, book_id: str, payload: dict[str, Any]) -> None:
    for q in state.event_subscribers.get(book_id, []):
        await q.put(payload)


def _schedule_classify(state: AppState, book_id: str) -> None:
    title = book_title(state.conn, book_id)

    async def _run() -> None:
        record = register_book_task(
            state.task_registry,
            kind="classify",
            book_id=book_id,
            subject_label=title,
            detail="LLM 分类",
            profile="summarize",
            status="queued",
        )
        state.task_registry.mark_running(record.id)
        try:
            category = await run_classify_book(
                state.conn,
                state.router,
                book_id,
                prompts=_prompts(state),
            )
            if category:
                state.task_registry.update_resource(record.id, state.router.last_resource_id)
                await _emit_book_event(
                    state,
                    book_id,
                    {"type": "book_classified", "category": category},
                )
            state.task_registry.complete(record.id)
        except Exception as exc:
            state.task_registry.fail(record.id, str(exc))

    asyncio.create_task(_run())


def _book_ingest_error(conn, book_id: str) -> str | None:
    row = BookRepo(conn).get(book_id)
    if not row:
        return None
    raw = row.get("metadata_json")
    meta: dict[str, Any] = {}
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                meta = parsed
        except (json.JSONDecodeError, TypeError):
            meta = {}
    elif isinstance(raw, dict):
        meta = raw
    err = meta.get("ingest_error") or meta.get("resegment_error")
    if isinstance(err, str) and err.strip():
        return err.strip()
    return None


async def _await_cpu_lock(state: AppState, queued_book_id: str) -> None:
    queued = {
        "type": "ingest_progress",
        "page": 0,
        "total": 0,
        "message": "排队等待分段…",
    }
    if state.cpu_job_lock.locked():
        await _emit_book_event(state, queued_book_id, queued)
    while True:
        try:
            await asyncio.wait_for(state.cpu_job_lock.acquire(), timeout=1.0)
            return
        except TimeoutError:
            await _emit_book_event(state, queued_book_id, queued)


def _schedule_ingest(
    state: AppState,
    *,
    book_id: str,
    dest: Path,
    fmt: str,
    src: Path,
) -> None:
    cancel_event = threading.Event()
    title = book_title(state.conn, book_id)
    record = state.task_registry.register(
        kind="ingest",
        subject_type="book",
        subject_id=book_id,
        subject_label=title,
        detail="导入解析",
        cancellable=True,
        cancel_fn=cancel_event.set,
        job_key=f"{book_id}:ingest",
        status="queued",
    )

    async def _run() -> str:
        await _await_cpu_lock(state, book_id)
        try:
            state.task_registry.mark_running(record.id)
            outcome = await run_ingest_job(
                book_id=book_id,
                dest=dest,
                fmt=fmt,
                src=src,
                conn=state.conn,
                db_path=state.db_path,
                models=state.models,
                settings=state.settings.model_copy(deep=True),
                target_language=state.settings.target_language,
                job_queue=state.job_queue,
                emit=lambda event_book_id, payload: _emit_book_event(
                    state, event_book_id, payload
                ),
                schedule_classify=lambda bid: _schedule_classify(state, bid),
                cancel_event=cancel_event,
            )
            if outcome == "completed":
                state.task_registry.complete(record.id)
            elif outcome == "cancelled":
                state.task_registry.cancel(record.id)
            else:
                reason = await asyncio.to_thread(_book_ingest_error, state.conn, book_id)
                state.task_registry.fail(record.id, reason or "导入失败")
            return outcome
        finally:
            state.cpu_job_lock.release()

    task = asyncio.create_task(_run())
    state.ingest_tasks[book_id] = task
    state.ingest_cancel_events[book_id] = cancel_event

    def _cleanup(completed: asyncio.Task[str]) -> None:
        if state.ingest_tasks.get(book_id) is completed:
            state.ingest_tasks.pop(book_id, None)
            state.ingest_cancel_events.pop(book_id, None)

    task.add_done_callback(_cleanup)


def _schedule_resegment(
    state: AppState,
    *,
    book_id: str,
    chunk_target_chars: int,
    previous_status: str,
    segment_tier: str = "normal",
) -> None:
    cancel_event = threading.Event()
    title = book_title(state.conn, book_id)
    resolved_tier = normalize_segment_tier(segment_tier)
    detail = f"整书重新分段 · 目标 {chunk_target_chars} 字"
    if resolved_tier == "advanced":
        detail += " · 高级"
    record = state.task_registry.register(
        kind="resegment",
        subject_type="book",
        subject_id=book_id,
        subject_label=title,
        detail=detail,
        cancellable=True,
        cancel_fn=cancel_event.set,
        job_key=f"{book_id}:resegment",
        status="queued",
    )

    async def _run() -> str:
        await _await_cpu_lock(state, book_id)
        try:
            state.task_registry.mark_running(record.id)
            outcome = await run_resegment_job(
                book_id=book_id,
                chunk_target_chars=chunk_target_chars,
                previous_status=previous_status,
                conn=state.conn,
                db_path=state.db_path,
                settings=state.settings.model_copy(deep=True),
                job_queue=state.job_queue,
                emit=lambda event_book_id, payload: _emit_book_event(
                    state, event_book_id, payload
                ),
                cancel_event=cancel_event,
                segment_tier=resolved_tier,
            )
            if outcome == "completed":
                state.task_registry.complete(record.id)
            elif outcome == "cancelled":
                state.task_registry.cancel(record.id)
            else:
                reason = await asyncio.to_thread(_book_ingest_error, state.conn, book_id)
                state.task_registry.fail(record.id, reason or "重新分段失败")
            return outcome
        finally:
            state.cpu_job_lock.release()

    task = asyncio.create_task(_run())
    state.resegment_tasks[book_id] = task
    state.resegment_cancel_events[book_id] = cancel_event

    def _cleanup(completed: asyncio.Task[str]) -> None:
        if state.resegment_tasks.get(book_id) is completed:
            state.resegment_tasks.pop(book_id, None)
            state.resegment_cancel_events.pop(book_id, None)

    task.add_done_callback(_cleanup)


def _probe_resource_with_overrides(resource, body: ContextProbeRequest):
    updates: dict[str, Any] = {}
    if body.model is not None and body.model.strip():
        updates["model"] = body.model.strip()
    if body.base_url is not None and body.base_url.strip():
        updates["base_url"] = body.base_url.strip()
    key = (body.api_key or "").strip()
    if key and key != "***":
        updates["api_key"] = key
    if not updates:
        return resource
    return resource.model_copy(update=updates)


def _schedule_context_probe(state: AppState, resource) -> None:
    resource_id = resource.id
    cancel_event = asyncio.Event()
    status = ContextProbeStatus(
        resource_id=resource_id,
        status="running",
        model=resource.model,
        message="正在测试后面的段是否仍被理解…",
    )
    state.context_probe_status[resource_id] = status
    state.context_probe_cancel[resource_id] = cancel_event

    async def _run() -> None:
        try:
            await run_context_probe(
                router=state.router,
                resource=resource,
                status=status,
                cancel_event=cancel_event,
            )
        except Exception as exc:
            status.status = "failed"
            status.waiting_for_slot = False
            status.message = str(exc).strip()[:240] or "上下文探测失败"

    task = asyncio.create_task(_run())
    state.context_probe_tasks[resource_id] = task

    def _cleanup(completed: asyncio.Task) -> None:
        if state.context_probe_tasks.get(resource_id) is completed:
            state.context_probe_tasks.pop(resource_id, None)
            state.context_probe_cancel.pop(resource_id, None)

    task.add_done_callback(_cleanup)


_PROCESS_START_MONO = time.perf_counter()
_PROCESS_STARTED_AT = int(time.time())


def _sidecar_executable() -> str:
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable)
    return os.path.abspath(sys.argv[0])


@router.get("/health")
async def health() -> dict[str, str | int]:
    return {
        "status": "ok",
        "pid": os.getpid(),
        "chunker_version": CHUNKER_VERSION,
        "core_version": CORE_VERSION,
        "executable": _sidecar_executable(),
        "started_at": _PROCESS_STARTED_AT,
        "uptime_ms": int((time.perf_counter() - _PROCESS_START_MONO) * 1000),
    }


@router.get("/startup/status")
async def startup_status(request: Request) -> dict[str, Any]:
    """Cold-start phases: engine/data/cache gate product-ready; news is background."""
    return _state(request).startup_status()


@router.post("/books/import")
async def import_books(body: ImportRequest, request: Request) -> dict[str, Any]:
    state = _state(request)
    results: list[dict[str, Any]] = []
    books_repo = BookRepo(state.conn)
    _wire_job_events(state)

    for path_str in body.paths:
        src = Path(path_str).expanduser().resolve()
        if not src.exists():
            raise HTTPException(400, f"File not found: {src}")
        try:
            validate_import(src)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

        digest = await asyncio.to_thread(file_hash, src)
        existing = books_repo.find_by_hash(digest)
        if existing and not body.overwrite:
            raise HTTPException(
                409,
                detail={"existing_book_id": existing["id"], "title": existing["title"]},
            )
        if existing and body.overwrite:
            await _purge_book(state, existing["id"])

        fmt = detect_format(src)
        if fmt not in SUPPORTED_FORMATS:
            raise HTTPException(400, f"Unsupported format: {fmt}")

        try:
            book_id = str(uuid.uuid4())
            dest = await asyncio.to_thread(
                copy_to_library, src, state.books_dir, book_id
            )
            title = title_from_path(src, None)
            book = books_repo.insert(
                id=book_id,
                title=title,
                author=None,
                format=fmt,
                file_path=str(dest),
                file_hash=digest,
                language=None,
                target_language=state.settings.target_language,
                segment_count=0,
                status="processing",
                metadata_json={"source_filename": src.name},
            )
            results.append(
                {"book_id": book_id, "status": "processing", "title": book["title"]}
            )
            _schedule_ingest(
                state,
                book_id=book_id,
                dest=dest,
                fmt=fmt,
                src=src,
            )
        except HTTPException:
            raise
        except RuntimeError as e:
            raise HTTPException(400, str(e)) from e
        except Exception as e:
            raise HTTPException(400, f"导入失败: {e}") from e

    return {"books": results}


@router.post("/books/{book_id}/import/overwrite")
async def overwrite_book(book_id: str, body: ImportRequest, request: Request) -> dict[str, Any]:
    body.overwrite = True
    return await import_books(body, request)


@router.get("/books")
async def list_books(
    request: Request,
    filter: str = Query("all"),
    sort: str = Query("recent"),
) -> dict[str, Any]:
    state = _state(request)
    conn = state.conn
    try:
        await state.job_queue.resume_orphaned_active()
        live_ids = set(state.ingest_tasks) | set(state.resegment_tasks)
        active_by_book = state.job_queue.summarize_active_by_book()

        def _load_rows() -> list[dict[str, Any]]:
            repo = BookRepo(conn)
            repo.repair_stale_imports(live_ids)
            # document_tree strip runs once in deferred startup work — not every list.
            books = repo.list_books(filter=filter, sort=sort)
            rows: list[dict[str, Any]] = []
            for book in books:
                row = dict(book)
                ready = row.get("summary_ready_count")
                total = row.get("summary_total_count")
                segment_count = int(row.get("segment_count") or 0)
                # Prefer denormalized columns; repair only when they drifted.
                if (
                    ready is None
                    or total is None
                    or int(total) != segment_count
                ):
                    row.update(repo.refresh_summary_progress(book["id"]))
                else:
                    row["summary_ready_count"] = int(ready or 0)
                    row["summary_total_count"] = int(total or 0)
                rows.append(row)
            return rows

        rows = await asyncio.to_thread(_load_rows)
        # Queue fields stay in-memory. Do not call summarize_state_by_book()
        # here: that re-scans every book on the event loop (N+1 COUNT) and
        # stalls POST /open while the library polls during 分段中.
        result = [
            book_public_dict(
                b,
                summarize_active=active_by_book.get(b["id"]),
                summarize_state=state.job_queue.summarize_state_for_book(
                    b["id"],
                    ready=int(b.get("summary_ready_count") or 0),
                    total=int(b.get("summary_total_count") or 0),
                ),
                summarize_queued_count=state.job_queue._summarize_queued_count_for_book(
                    b["id"]
                ),
                summary_tier=state.job_queue._desired_summary_tier.get(
                    b["id"], "normal"
                ),
                processing_kind=_processing_kind(state, b["id"]),
            )
            for b in rows
        ]
        result = apply_book_list_filter(result, filter)
        if sort == "recent":
            result = _prioritize_summarize_activity(result)
        return {"books": result}
    except sqlite3.OperationalError as e:
        raise HTTPException(503, _SCHEMA_STALE_DETAIL) from e


@router.patch("/books/{book_id}")
async def patch_book(
    book_id: str, body: BookPatchUpdate, request: Request
) -> dict[str, Any]:
    state = _state(request)
    repo = BookRepo(state.conn)
    book = repo.get(book_id)
    if not book:
        raise HTTPException(404, "Book not found")

    updates: dict[str, Any] = {}
    if body.is_favorite is not None:
        updates["is_favorite"] = 1 if body.is_favorite else 0
    if body.category is not None:
        updates["category"] = validate_manual_category(body.category)
    if body.title is not None:
        title = body.title.strip()
        if not title:
            raise HTTPException(400, "title cannot be empty")
        updates["title"] = title
        updates["metadata_json"] = metadata_with_title_user_set(book)

    if not updates:
        return _book_public_with_queue(state, book)

    def _persist() -> dict[str, Any] | None:
        repo.update(book_id, **updates)
        updated = repo.get(book_id)
        if updated and "title" in updates:
            index_book(state.conn, updated)
        return updated

    updated = await asyncio.to_thread(_persist)
    return _book_public_with_queue(state, updated)  # type: ignore[arg-type]


@router.delete("/books/{book_id}")
async def delete_book(book_id: str, request: Request) -> dict[str, str]:
    state = _state(request)
    book = BookRepo(state.conn).get(book_id)
    if not book:
        raise HTTPException(404, "Book not found")

    await _purge_book(state, book_id)
    return {"status": "deleted"}


@router.post("/books/{book_id}/resegment", status_code=202)
async def resegment_book(
    book_id: str, body: ResegmentRequest, request: Request
) -> dict[str, int | str]:
    state = _state(request)
    book = await asyncio.to_thread(BookRepo(state.conn).get, book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    if book.get("status") == "processing":
        raise HTTPException(409, "Book is already processing")
    file_path = Path(str(book.get("file_path") or ""))
    if not book.get("file_path") or not await asyncio.to_thread(file_path.exists):
        raise HTTPException(400, "Original book file is missing")

    previous_status = str(book.get("status") or "reading")
    _wire_job_events(state)
    claimed = await asyncio.to_thread(BookRepo(state.conn).claim_processing, book_id)
    if not claimed:
        raise HTTPException(409, "Book is already processing")
    _schedule_resegment(
        state,
        book_id=book_id,
        chunk_target_chars=body.chunk_target_chars,
        previous_status=previous_status,
        segment_tier=body.segment_tier,
    )
    return {
        "status": "processing",
        "book_id": book_id,
        "chunk_target_chars": body.chunk_target_chars,
        "segment_tier": body.segment_tier,
        "processing_kind": "resegment",
    }


@router.post("/books/{book_id}/ingest/cancel", status_code=202)
async def cancel_ingest_book(
    book_id: str, request: Request
) -> dict[str, str]:
    state = _state(request)
    book = await asyncio.to_thread(BookRepo(state.conn).get, book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    cancel_event = state.ingest_cancel_events.get(book_id)
    task = state.ingest_tasks.get(book_id)
    if cancel_event is None or task is None or task.done():
        raise HTTPException(409, "Book is not being imported")
    cancel_event.set()
    return {"status": "cancelling", "book_id": book_id}


@router.post("/books/{book_id}/resegment/cancel", status_code=202)
async def cancel_resegment_book(
    book_id: str, request: Request
) -> dict[str, str]:
    state = _state(request)
    book = await asyncio.to_thread(BookRepo(state.conn).get, book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    cancel_event = state.resegment_cancel_events.get(book_id)
    task = state.resegment_tasks.get(book_id)
    if cancel_event is None or task is None or task.done():
        raise HTTPException(409, "Book is not being resegmented")
    cancel_event.set()
    return {"status": "cancelling", "book_id": book_id}


@router.post("/books/{book_id}/classify")
async def classify_book_endpoint(book_id: str, request: Request) -> dict[str, str]:
    state = _state(request)
    book = BookRepo(state.conn).get(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    _schedule_classify(state, book_id)
    return {"status": "queued"}


@router.get("/books/categories")
async def list_book_categories() -> dict[str, list[str]]:
    return {"categories": list(BOOK_CATEGORIES)}


@router.get("/books/{book_id}")
async def get_book(book_id: str, request: Request) -> dict[str, Any]:
    state = _state(request)

    def _load_book() -> dict[str, Any] | None:
        book = BookRepo(state.conn).get(book_id)
        if not book:
            return None
        progress = BookRepo(state.conn).summary_progress(book_id)
        out = dict(book)
        out.update(progress)
        return out

    # Off-loop: shared SQLite may be locked by ingest/persist worker threads.
    book = await asyncio.to_thread(_load_book)
    if not book:
        raise HTTPException(404, "Book not found")
    ready = int(book.get("summary_ready_count") or 0)
    total = int(book.get("summary_total_count") or 0)
    return book_public_dict(
        book,
        summarize_active=state.job_queue.summarize_active_for_book(book_id),
        summarize_state=state.job_queue.summarize_state_for_book(
            book_id, ready=ready, total=total
        ),
        summarize_queued_count=state.job_queue._summarize_queued_count_for_book(
            book_id
        ),
        processing_kind=_processing_kind(state, book_id),
    )


@router.get("/books/{book_id}/segments")
async def list_segments(
    book_id: str,
    request: Request,
    include_summary: bool = Query(False),
    around: int | None = Query(None),
    after_idx: int | None = Query(None),
    before_idx: int | None = Query(None),
    limit: int | None = Query(None),
) -> dict[str, Any]:
    # Slim meta — raw_text/translation/summary_json via GET .../segments/{idx} (never-freeze).
    # Reader open must use around/after_idx/before_idx (O(limit)); full list is export/compat only.
    repo = SegmentRepo(_state(request).conn)
    windowed = around is not None or after_idx is not None or before_idx is not None

    def _list_meta() -> dict[str, Any]:
        try:
            if include_summary and not windowed:
                segments = repo.list_for_book(
                    book_id, include_body=False, include_summary=True
                )
                return {
                    "segments": segments,
                    "total": len(segments),
                    "has_more_before": False,
                    "has_more_after": False,
                }
            if windowed or limit is not None:
                page_limit = (
                    CATALOG_WINDOW_DEFAULT
                    if around is not None and limit is None
                    else CATALOG_PAGE_DEFAULT
                    if limit is None
                    else limit
                )
                return repo.list_catalog_page(
                    book_id,
                    around=around,
                    after_idx=after_idx,
                    before_idx=before_idx,
                    limit=page_limit,
                )
            segments = repo.list_catalog(book_id)
            return {
                "segments": segments,
                "total": len(segments),
                "has_more_before": False,
                "has_more_after": False,
            }
        except sqlite3.OperationalError as e:
            _raise_on_db_schema_error(e)
            raise  # pragma: no cover

    return await asyncio.to_thread(_list_meta)


@router.get("/books/{book_id}/original-search")
async def search_book_original(
    book_id: str,
    request: Request,
    q: str = Query(""),
) -> dict[str, Any]:
    state = _state(request)

    def _run() -> dict[str, Any]:
        book = BookRepo(state.conn).get(book_id)
        if not book:
            return {"missing_book": True}
        result = search_original(state.conn, book_id, q)
        return result

    payload = await asyncio.to_thread(_run)
    if payload.pop("missing_book", False):
        raise HTTPException(404, "Book not found")
    return payload


@router.get("/books/{book_id}/segments/{idx}")
async def get_segment(book_id: str, idx: int, request: Request) -> dict[str, Any]:
    seg = await asyncio.to_thread(
        SegmentRepo(_state(request).conn).get_by_index, book_id, idx
    )
    if not seg:
        raise HTTPException(404, "Segment not found")
    return seg


@router.get("/books/{book_id}/segments/{idx}/summary")
async def get_segment_summary(book_id: str, idx: int, request: Request) -> dict[str, Any]:
    seg = await asyncio.to_thread(
        SegmentRepo(_state(request).conn).get_summary_by_index, book_id, idx
    )
    if not seg:
        raise HTTPException(404, "Segment not found")
    return seg


def _normalize_listen_mode(mode: str) -> ListenMode:
    normalized = (mode or "").strip().lower()
    if normalized not in LISTEN_MODES:
        raise HTTPException(400, "mode must be summary, detailed, or original")
    return normalized  # type: ignore[return-value]


def _listen_language_hint(state: AppState) -> str | None:
    lang = (state.settings.target_language or "").lower()
    if lang.startswith("zh"):
        return "zh"
    if lang.startswith("en"):
        return "en"
    return None


@router.get("/books/{book_id}/segments/{idx}/listen-script")
async def get_listen_script(
    book_id: str,
    idx: int,
    request: Request,
    mode: str = Query("summary"),
) -> dict[str, Any]:
    typed = _normalize_listen_mode(mode)
    state = _state(request)
    repo = SegmentRepo(state.conn)

    def _load() -> dict[str, Any]:
        script, row = load_listen_script(
            repo,
            book_id,
            idx,
            typed,
            language_hint=_listen_language_hint(state),
        )
        if row is None and script.skip_reason == "missing_segment":
            return {"missing": True}
        payload = script.to_dict()
        payload["idx"] = idx
        return payload

    payload = await asyncio.to_thread(_load)
    if payload.get("missing"):
        raise HTTPException(404, "Segment not found")
    return payload


def _boundary_pair(
    conn: sqlite3.Connection, book_id: str, idx: int
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    book = BookRepo(conn).get(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    if book.get("status") == "processing":
        raise HTTPException(409, "Book is still processing")
    repo = SegmentRepo(conn)
    left = repo.get_by_index(book_id, idx)
    right = repo.get_by_index(book_id, idx + 1)
    if not left or not right:
        raise HTTPException(404, "Adjacent segments not found")
    return book, left, right


def _boundary_payload(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    oversized: bool = False,
    unchanged: bool = False,
) -> dict[str, Any]:
    return {
        "left_idx": left["idx"],
        "right_idx": right["idx"],
        "left_char_count": left.get("char_count") or len(left.get("raw_text") or ""),
        "right_char_count": right.get("char_count") or len(right.get("raw_text") or ""),
        "left_anchor_label": left.get("anchor_label"),
        "right_anchor_label": right.get("anchor_label"),
        "left_chapter": left.get("chapter"),
        "right_chapter": right.get("chapter"),
        "left_page_range": left.get("page_range"),
        "right_page_range": right.get("page_range"),
        "left_status": left.get("summary_status"),
        "right_status": right.get("summary_status"),
        "oversized": oversized,
        "unchanged": unchanged,
        "oversized_limit": CHUNK_MAX_CHARS,
    }


@router.get("/books/{book_id}/segments/{idx}/boundary")
async def get_segment_boundary(
    book_id: str, idx: int, request: Request
) -> dict[str, Any]:
    state = _state(request)

    def _load() -> dict[str, Any]:
        _book, left, right = _boundary_pair(state.conn, book_id, idx)
        concat = f"{left.get('raw_text') or ''}{right.get('raw_text') or ''}"
        current = len(left.get("raw_text") or "")
        candidates = [
            {"offset": item.offset, "kind": item.kind}
            for item in list_cut_offsets(concat, current_offset=current)
        ]
        return {
            "left_idx": idx,
            "right_idx": idx + 1,
            "total_chars": len(concat),
            "left_char_count": current,
            "candidates": candidates,
            "oversized_limit": CHUNK_MAX_CHARS,
        }

    try:
        return await asyncio.to_thread(_load)
    except HTTPException:
        raise
    except sqlite3.OperationalError as exc:
        _raise_on_db_schema_error(exc)
        raise  # pragma: no cover


@router.post("/books/{book_id}/segments/{idx}/boundary")
async def move_segment_boundary(
    book_id: str, idx: int, body: MoveBoundaryRequest, request: Request
) -> dict[str, Any]:
    state = _state(request)
    if book_id in state.resegment_tasks:
        raise HTTPException(409, "Book is being resegmented")

    def _persist() -> tuple[dict[str, Any], dict[str, Any], bool, bool]:
        book, left, right = _boundary_pair(state.conn, book_id, idx)
        try:
            moved = apply_cut(
                left.get("raw_text") or "",
                right.get("raw_text") or "",
                body.left_char_count,
            )
        except BoundaryError as exc:
            raise HTTPException(400, str(exc)) from exc
        if moved.unchanged:
            return left, right, False, False
        left_anchor = segment_anchor_label(
            left["idx"], moved.left_chapter, moved.left_page_range
        )
        right_anchor = segment_anchor_label(
            right["idx"], moved.right_chapter, moved.right_page_range
        )
        summary_tier = (
            left.get("summary_tier") or right.get("summary_tier") or "normal"
        )
        updated_left, updated_right = SegmentRepo(state.conn).apply_boundary_move(
            left,
            right,
            left_text=moved.left_text,
            right_text=moved.right_text,
            left_chapter=moved.left_chapter,
            right_chapter=moved.right_chapter,
            left_page_range=moved.left_page_range,
            right_page_range=moved.right_page_range,
            left_anchor=left_anchor,
            right_anchor=right_anchor,
            summary_tier=summary_tier,
        )
        index_segment(state.conn, book, updated_left)
        index_segment(state.conn, book, updated_right)
        return updated_left, updated_right, moved.oversized, True

    try:
        left, right, oversized, changed = await asyncio.to_thread(_persist)
    except HTTPException:
        raise
    except sqlite3.OperationalError as exc:
        _raise_on_db_schema_error(exc)
        raise  # pragma: no cover

    _wire_job_events(state)
    if changed:
        state.job_queue.cancel_active_jobs_for_segments(
            book_id, {left["id"], right["id"]}
        )
        await _queue_segment_retry(state, book_id, idx, seg=left)
        payload = _boundary_payload(
            left, right, oversized=oversized, unchanged=False
        )
        payload["type"] = "segment_boundary_moved"
        await state.job_queue.emit(book_id, payload)
        for side in (left, right):
            await state.job_queue.emit(
                book_id,
                {
                    "type": "segment_status",
                    "idx": side["idx"],
                    "status": "pending",
                },
            )
    return _boundary_payload(left, right, oversized=oversized, unchanged=not changed)


@router.post("/books/{book_id}/open")
async def open_book(book_id: str, request: Request) -> dict[str, Any]:
    state = _state(request)

    def _open_book() -> dict[str, Any] | None:
        repo = BookRepo(state.conn)
        book = repo.get(book_id)
        if not book:
            return None
        fields: dict[str, Any] = {"last_opened_at": _now_iso()}
        if book.get("status") == "unread":
            fields["status"] = "reading"
        try:
            repo.update(book_id, **fields)
        except sqlite3.OperationalError as exc:
            raise HTTPException(503, _SCHEMA_STALE_DETAIL) from exc
        return book

    # Opening writes recency metadata and can wait behind an ingest writer.
    # Keep that wait off the single uvicorn event-loop thread.
    book = await asyncio.to_thread(_open_book)
    if not book:
        raise HTTPException(404, "Book not found")
    _wire_job_events(state)
    if state.job_queue.auto_start_summary:
        # Never block first paint on O(n) prefetch / recover scans.
        task = asyncio.create_task(
            state.job_queue.enqueue_book_prefetch(book_id),
            name=f"open-prefetch-{book_id[:8]}",
        )

        def _log_prefetch_error(done: asyncio.Task[None]) -> None:
            if done.cancelled():
                return
            exc = done.exception()
            if exc is not None:
                logger.error(
                    "open prefetch failed book_id=%s", book_id, exc_info=exc
                )

        task.add_done_callback(_log_prefetch_error)
    return {
        "status": "opened",
        "current_segment_index": book.get("current_segment_index") or 0,
    }


@router.patch("/books/{book_id}/reading-progress")
async def update_reading_progress(
    book_id: str, body: ReadingProgressUpdate, request: Request
) -> dict[str, int]:
    state = _state(request)

    def _save_progress() -> None:
        repo = BookRepo(state.conn)
        book = repo.get(book_id)
        if not book:
            raise HTTPException(404, "Book not found")
        segment_count = book.get("segment_count") or 0
        if segment_count > 0 and not (0 <= body.segment_index < segment_count):
            raise HTTPException(
                400,
                f"segment_index must be between 0 and {segment_count - 1}",
            )
        repo.update(
            book_id, current_segment_index=body.segment_index
        )

    await asyncio.to_thread(_save_progress)
    return {"current_segment_index": body.segment_index}


@router.get("/books/summarize/overview")
async def summarize_overview(request: Request) -> dict[str, Any]:
    state = _state(request)
    await state.job_queue.resume_orphaned_active()
    return await asyncio.to_thread(state.job_queue.summarize_overview)


@router.post("/books/summarize/start")
async def start_summarize_batch(
    request: Request, body: SummarizeBatchRequest | None = None
) -> dict[str, Any]:
    state = _state(request)
    _wire_job_events(state)
    book_ids = body.book_ids if body else []
    summary_tier = body.summary_tier if body else "normal"
    if not book_ids:
        await state.job_queue.start_all(summary_tier=summary_tier)
        return {
            "status": "started",
            "scope": "all",
            "book_ids": [],
            "affected_count": 0,
            "summary_tier": summary_tier,
        }

    repo = BookRepo(state.conn)
    affected: list[str] = []
    skipped: list[str] = []
    for book_id in book_ids:
        if not await asyncio.to_thread(repo.get, book_id):
            skipped.append(book_id)
            continue
        await state.job_queue.start_book(book_id, summary_tier=summary_tier)
        affected.append(book_id)
    return {
        "status": "started",
        "scope": "batch",
        "book_ids": affected,
        "affected_count": len(affected),
        "skipped": skipped,
        "summary_tier": summary_tier,
    }


@router.post("/books/summarize/stop")
async def stop_summarize_batch(
    request: Request, body: SummarizeBatchRequest | None = None
) -> dict[str, Any]:
    state = _state(request)
    _wire_job_events(state)
    book_ids = body.book_ids if body else []
    if not book_ids:
        await state.job_queue.stop_all()
        return {"status": "stopped", "scope": "all", "book_ids": [], "affected_count": 0}

    repo = BookRepo(state.conn)
    affected: list[str] = []
    skipped: list[str] = []
    for book_id in book_ids:
        if not await asyncio.to_thread(repo.get, book_id):
            skipped.append(book_id)
            continue
        await state.job_queue.stop_book(book_id)
        affected.append(book_id)
    return {
        "status": "stopped",
        "scope": "batch",
        "book_ids": affected,
        "affected_count": len(affected),
        "skipped": skipped,
    }


@router.post("/books/{book_id}/summarize/start")
async def start_summarize_book(
    book_id: str, request: Request, body: SummaryTierRequest | None = None
) -> dict[str, str]:
    """Resume incomplete summaries. Ready segments are kept even if the tier changes."""
    state = _state(request)
    book = await asyncio.to_thread(BookRepo(state.conn).get, book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    _wire_job_events(state)
    summary_tier = body.summary_tier if body else "normal"
    await state.job_queue.start_book(book_id, summary_tier=summary_tier)
    return {
        "status": "started",
        "scope": "book",
        "book_id": book_id,
        "summary_tier": summary_tier,
    }


@router.post("/books/{book_id}/index")
async def build_book_index(book_id: str, request: Request) -> dict[str, Any]:
    """Queue the whole-book index. Only "chat with whole book" needs it.

    This is the single entry point: nothing enqueues rollup automatically, so a
    library full of summarized books never floods the queue on startup.
    """
    state = _state(request)
    repo = BookRepo(state.conn)
    book = await asyncio.to_thread(repo.get, book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    _wire_job_events(state)
    progress = await asyncio.to_thread(repo.summary_progress, book_id)
    ready = int(progress["summary_ready_count"] or 0)
    total = int(progress["summary_total_count"] or 0)
    if total <= 0 or ready < total:
        raise HTTPException(409, f"摘要未完成（{ready}/{total}），无法建全书索引")
    await state.job_queue.enqueue_rollup(book_id)
    refreshed = await asyncio.to_thread(repo.get, book_id) or book
    return {
        "status": "queued",
        "book_id": book_id,
        "index_status": refreshed.get("index_status") or "idle",
    }


@router.post("/books/{book_id}/summarize/stop")
async def stop_summarize_book(book_id: str, request: Request) -> dict[str, str]:
    state = _state(request)
    book = await asyncio.to_thread(BookRepo(state.conn).get, book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    _wire_job_events(state)
    await state.job_queue.stop_book(book_id)
    return {"status": "stopped", "scope": "book", "book_id": book_id}


@router.post("/books/{book_id}/segments/{idx}/retry")
async def retry_segment(
    book_id: str,
    idx: int,
    request: Request,
    body: SummaryTierRequest | None = None,
) -> dict[str, str]:
    state = _state(request)
    await _queue_segment_retry(
        state,
        book_id,
        idx,
        summary_tier=body.summary_tier if body else None,
    )
    return {"status": "queued"}


@router.post("/books/{book_id}/segments/retry")
async def retry_segments(
    book_id: str, body: RetrySegmentsRequest, request: Request
) -> dict[str, int | str]:
    state = _state(request)
    book = await asyncio.to_thread(BookRepo(state.conn).get, book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    indices = sorted(set(body.indices))
    if not indices:
        raise HTTPException(400, "indices must not be empty")
    def _load_segments() -> list[tuple[int, dict[str, Any]]]:
        seg_repo = SegmentRepo(state.conn)
        loaded: list[tuple[int, dict[str, Any]]] = []
        for idx in indices:
            seg = seg_repo.get_by_index(book_id, idx)
            if not seg:
                raise HTTPException(400, f"Segment not found: {idx}")
            loaded.append((idx, seg))
        return loaded

    segments = await asyncio.to_thread(_load_segments)
    _wire_job_events(state)
    for idx, seg in segments:
        await _queue_segment_retry(
            state,
            book_id,
            idx,
            seg=seg,
            summary_tier=body.summary_tier,
        )
    return {"status": "queued", "count": len(segments)}


@router.post("/books/{book_id}/summarize/regenerate")
async def regenerate_book_summaries(
    book_id: str, request: Request, body: SummaryTierRequest | None = None
) -> dict[str, int | str]:
    """Overwrite every segment summary. Clients must confirm with the user first."""
    state = _state(request)
    repo = BookRepo(state.conn)
    book = await asyncio.to_thread(repo.get, book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    _wire_job_events(state)
    if book.get("status") == "summarized":
        await asyncio.to_thread(repo.update, book_id, status="reading")
    summary_tier = body.summary_tier if body else "normal"
    count = await state.job_queue.enqueue_book_regenerate(
        book_id, summary_tier=summary_tier
    )
    return {"status": "queued", "count": count, "summary_tier": summary_tier}


@router.get("/books/{book_id}/events")
async def book_events(book_id: str, request: Request) -> StreamingResponse:
    state = _state(request)
    queue: asyncio.Queue = asyncio.Queue()
    state.event_subscribers.setdefault(book_id, []).append(queue)

    async def stream():
        try:
            # Progress-only snapshot — never dump O(n) segment rows on connect.
            progress = await asyncio.to_thread(
                BookRepo(state.conn).summary_progress, book_id
            )
            yield (
                "data: "
                + json.dumps(
                    {
                        "type": "snapshot",
                        "summary_ready_count": progress["summary_ready_count"],
                        "summary_total_count": progress["summary_total_count"],
                    },
                    ensure_ascii=False,
                )
                + "\n\n"
            )
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            subs = state.event_subscribers.get(book_id, [])
            if queue in subs:
                subs.remove(queue)

    return StreamingResponse(stream(), media_type="text/event-stream")


BOOK_INDEX_NOT_READY = "全书索引未就绪，请先建索引（POST /books/{book_id}/index）"


def _require_book_chat_index(book: dict[str, Any], scope: str) -> None:
    if scope != "book":
        return
    if book.get("index_status") == "ready":
        return
    raise HTTPException(409, BOOK_INDEX_NOT_READY)


@router.post("/books/{book_id}/chat")
async def book_chat(book_id: str, body: ChatRequest, request: Request):
    state = _state(request)
    book = BookRepo(state.conn).get(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    _require_book_chat_index(book, body.scope)

    if body.stream:
        return await book_chat_stream(book_id, body, request)

    title = book.get("title") or book_id
    segment_detail = (
        "深聊 · 全书"
        if body.scope == "book"
        else f"深聊 · 段 {body.segment_index + 1}"
    )
    record = register_book_task(
        state.task_registry,
        kind="book_chat",
        book_id=book_id,
        subject_label=title,
        detail=segment_detail,
        profile="chat",
        status="running",
    )
    state.job_queue.pause_ollama()
    try:
        return await track_async_task(
            state.task_registry,
            record,
            chat_with_book(
                state.router,
                ChatRepo(state.conn),
                SegmentRepo(state.conn),
                book=book,
                message=body.message,
                current_segment_idx=body.segment_index,
                quote=body.quote,
                scope=body.scope,
                web_search_provider=state.settings.web_search_provider,
                tavily_api_key=state.settings.tavily_api_key,
                web_search_enabled=state.settings.web_search_enabled,
                prompts=_prompts(state),
            ),
            router_resource=lambda: state.router.last_resource_id,
        )
    finally:
        state.job_queue.resume_ollama()


async def book_chat_stream(book_id: str, body: ChatRequest, request: Request) -> StreamingResponse:
    state = _state(request)
    book = BookRepo(state.conn).get(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    _require_book_chat_index(book, body.scope)

    title = book.get("title") or book_id
    segment_detail = (
        "深聊 · 全书"
        if body.scope == "book"
        else f"深聊 · 段 {body.segment_index + 1}"
    )
    cancel_event = asyncio.Event()
    record = register_book_task(
        state.task_registry,
        kind="book_chat",
        book_id=book_id,
        subject_label=title,
        detail=segment_detail,
        profile="chat",
        cancellable=True,
        cancel_fn=cancel_event.set,
        status="running",
    )

    async def stream():
        state.job_queue.pause_ollama()
        try:
            event_stream = stream_chat_with_book(
                state.router,
                ChatRepo(state.conn),
                SegmentRepo(state.conn),
                book=book,
                message=body.message,
                current_segment_idx=body.segment_index,
                quote=body.quote,
                scope=body.scope,
                web_search_provider=state.settings.web_search_provider,
                tavily_api_key=state.settings.tavily_api_key,
                web_search_enabled=state.settings.web_search_enabled,
                prompts=_prompts(state),
            )
            async for event in track_stream_events(
                state.task_registry,
                record,
                event_stream,
                cancel_event=cancel_event,
                router_resource=lambda: state.router.last_resource_id,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': f'深聊失败：{exc}'}, ensure_ascii=False)}\n\n"
        finally:
            state.job_queue.resume_ollama()

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/books/{book_id}/export")
async def export_book(book_id: str, body: ExportRequest, request: Request) -> PlainTextResponse:
    state = _state(request)
    book = BookRepo(state.conn).get(book_id)
    if not book:
        raise HTTPException(404, "Book not found")

    def _build_markdown() -> str:
        segments = SegmentRepo(state.conn).list_for_export(book_id)
        want_notes = body.include_notes and body.mode != "sentences"
        notes = NoteRepo(state.conn).list_for_book(book_id) if want_notes else None
        return export_book_markdown(
            book,
            segments,
            include_notes=want_notes,
            notes=notes,
            mode=body.mode,
        )

    md = await asyncio.to_thread(_build_markdown)
    suffix = "总结" if body.mode == "sentences" else "summary"
    filename = f"{book.get('title', 'book')}-{suffix}.md"
    return PlainTextResponse(
        md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": content_disposition_attachment(filename)},
    )


@router.get("/settings")
async def get_settings(request: Request) -> dict[str, Any]:
    state = _state(request)
    payload = settings_public_dict(state.settings)
    payload["models"] = models_to_dict(state.models)
    return payload


@router.put("/settings")
async def update_settings(body: SettingsUpdate, request: Request) -> dict[str, Any]:
    state = _state(request)
    if body.target_language is not None:
        state.settings.target_language = body.target_language
        state.job_queue.target_language = body.target_language
    if body.web_search_provider is not None:
        state.settings.web_search_provider = normalize_web_search_provider(body.web_search_provider)
    if body.web_search_enabled is not None:
        state.settings.web_search_enabled = body.web_search_enabled
    if "tavily_api_key" in body.model_fields_set:
        state.settings.tavily_api_key = merge_tavily_api_key(
            body.tavily_api_key, state.settings.tavily_api_key
        )
    if body.ocr_cloud_base_url is not None:
        state.settings.ocr_cloud_base_url = body.ocr_cloud_base_url.strip()
    if body.ocr_cloud_model is not None:
        state.settings.ocr_cloud_model = body.ocr_cloud_model.strip()
    if "ocr_cloud_api_key" in body.model_fields_set:
        state.settings.ocr_cloud_api_key = merge_ocr_cloud_api_key(
            body.ocr_cloud_api_key, state.settings.ocr_cloud_api_key
        )
    if body.ocr_cloud_timeout_seconds is not None:
        state.settings.ocr_cloud_timeout_seconds = body.ocr_cloud_timeout_seconds
    if body.debug_mode is not None:
        state.settings.debug_mode = body.debug_mode
    if body.auto_start_summary is not None:
        state.settings.auto_start_summary = body.auto_start_summary
        state.job_queue.auto_start_summary = body.auto_start_summary
    if body.default_segment_tier is not None:
        state.settings.default_segment_tier = normalize_segment_tier(
            body.default_segment_tier
        )
    if body.prompts is not None:
        try:
            existing = _prompts(state)
            state.settings.prompts = merge_prompts(body.prompts, existing)
            state.job_queue.prompts = state.settings.prompts
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.models is not None:
        merged = merge_incoming_models(body.models, state.models)
        state.models = merged
        state.router.models = merged
        state.router.update_resources(merged.resources)
        state.job_queue.refresh_workers()
        save_models(state.settings.data_dir, merged)
    save_settings(state.settings)
    persist_secrets(state.settings.data_dir, state.models, state.settings)
    return await get_settings(request)


@router.get("/settings/resources/status")
async def all_resource_status(request: Request) -> dict[str, Any]:
    state = _state(request)
    results: list[dict[str, Any]] = []
    for resource in state.models.resources:
        status = await probe_resource(resource)
        results.append(status.to_dict())
    return {"resources": results}


@router.get("/settings/ocr/status")
async def ocr_status(request: Request) -> dict[str, Any]:
    return (await probe_ocr(_state(request).settings)).to_dict()


@router.get("/settings/resources/{resource_id}/status")
async def resource_status(resource_id: str, request: Request) -> dict[str, Any]:
    state = _state(request)
    resource = state.models.resource_by_id(resource_id)
    if resource is None:
        raise HTTPException(404, "Resource not found")
    status = await probe_resource(resource)
    return status.to_dict()


@router.get("/settings/resources/{resource_id}/context-probe")
async def get_context_probe(resource_id: str, request: Request) -> dict[str, Any]:
    state = _state(request)
    resource = state.models.resource_by_id(resource_id)
    if resource is None:
        raise HTTPException(404, "Resource not found")
    status = state.context_probe_status.get(resource_id)
    if status is None:
        return idle_probe_status(resource_id, resource.model).to_dict()
    return status.to_dict()


@router.post("/settings/resources/{resource_id}/context-probe", status_code=202)
async def start_context_probe(
    resource_id: str,
    request: Request,
    body: ContextProbeRequest | None = None,
) -> dict[str, Any]:
    state = _state(request)
    resource = state.models.resource_by_id(resource_id)
    if resource is None:
        raise HTTPException(404, "Resource not found")
    existing = state.context_probe_tasks.get(resource_id)
    if existing is not None and not existing.done():
        raise HTTPException(409, "Context probe already running")
    target = _probe_resource_with_overrides(resource, body or ContextProbeRequest())
    _schedule_context_probe(state, target)
    status = state.context_probe_status[resource_id]
    return {"status": "started", **status.to_dict()}


@router.post("/settings/resources/{resource_id}/context-probe/cancel", status_code=202)
async def cancel_context_probe(resource_id: str, request: Request) -> dict[str, str]:
    state = _state(request)
    resource = state.models.resource_by_id(resource_id)
    if resource is None:
        raise HTTPException(404, "Resource not found")
    task = state.context_probe_tasks.get(resource_id)
    cancel_event = state.context_probe_cancel.get(resource_id)
    if task is None or task.done() or cancel_event is None:
        raise HTTPException(409, "Context probe is not running")
    cancel_event.set()
    return {"status": "cancelling"}


@router.get("/settings/ollama/status")
async def ollama_status(request: Request, resource_id: str = "ollama") -> dict[str, Any]:
    state = _state(request)
    resource = state.models.resource_by_id(resource_id)
    if resource is None or resource.provider != "ollama":
        return {"skipped": True, "resource_id": resource_id}

    status = await probe_resource(resource)
    payload = status.to_dict()
    payload["skipped"] = False
    payload["served"] = status.probe_ok
    payload["model"] = resource.model or ""
    payload["probe_detail"] = status.message
    payload["selected_model"] = resource.model
    return payload


@router.get("/settings/resources/{resource_id}/ollama-status")
async def ollama_status_for_resource(resource_id: str, request: Request) -> dict[str, Any]:
    return await ollama_status(request, resource_id=resource_id)


@router.post("/shutdown")
async def shutdown(request: Request) -> dict[str, str]:
    server = getattr(request.app.state, "uvicorn_server", None)
    if server is not None:
        server.should_exit = True
    return {"status": "shutting_down"}


# --- Notes & Search ---


@router.post("/notes")
async def create_note(body: NoteCreate, request: Request) -> dict[str, Any]:
    state = _state(request)
    book = BookRepo(state.conn).get(body.book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    segment = SegmentRepo(state.conn).get(body.segment_id)
    if not segment or segment["book_id"] != body.book_id:
        raise HTTPException(400, "segment_id must belong to the book")

    def _persist() -> dict[str, Any]:
        note = NoteRepo(state.conn).create(
            book_id=body.book_id,
            content=body.content,
            note_type=body.type,
            segment_id=body.segment_id,
            quote=body.quote,
        )
        index_note(state.conn, book, note)
        return note

    return await asyncio.to_thread(_persist)


@router.get("/notes")
async def list_notes(
    request: Request,
    book_id: str | None = None,
    segment_id: str | None = None,
) -> dict[str, Any]:
    repo = NoteRepo(_state(request).conn)
    if book_id:
        notes = repo.list_for_book(book_id, segment_id=segment_id)
    else:
        notes = repo.list_all()
    return {"notes": notes}


@router.delete("/notes/{note_id}")
async def delete_note(note_id: str, request: Request) -> dict[str, str]:
    repo = NoteRepo(_state(request).conn)
    if not repo.get(note_id):
        raise HTTPException(404, "Note not found")
    repo.delete(note_id)
    return {"status": "deleted"}


@router.get("/search")
async def global_search(q: str, request: Request) -> dict[str, Any]:
    results = await asyncio.to_thread(search, _state(request).conn, q)
    return {"results": results}


# --- News lite ---


def _news_preset_urls() -> set[str]:
    return {url for url, _ in default_rss_sources()}


def _news_source_public(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["is_preset"] = out.get("url") in _news_preset_urls()
    return out


@router.get("/news/sources")
async def list_news_sources(request: Request) -> dict[str, Any]:
    conn = _state(request).conn

    def _load() -> list[dict[str, Any]]:
        return NewsSourceRepo(conn).list_sources()

    sources = await asyncio.to_thread(_load)
    return {"sources": [_news_source_public(s) for s in sources]}


@router.post("/news/sources")
async def add_news_source(body: NewsSourceCreate, request: Request) -> dict[str, Any]:
    url = body.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "URL must start with http:// or https://")
    repo = NewsSourceRepo(_state(request).conn)
    if repo.get_by_url(url):
        raise HTTPException(409, "Source URL already exists")
    try:
        source = repo.add_source(url, body.title.strip())
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "Source URL already exists") from exc
    return _news_source_public(source)


@router.post("/news/sources/restore-defaults")
async def restore_news_defaults(request: Request) -> dict[str, Any]:
    repo = NewsSourceRepo(_state(request).conn)
    restored = await asyncio.to_thread(repo.restore_defaults, default_rss_sources())
    sources = [_news_source_public(s) for s in repo.list_sources()]
    return {"restored": restored, "sources": sources}


@router.delete("/news/sources/{source_id}")
async def delete_news_source(source_id: str, request: Request) -> dict[str, str]:
    NewsSourceRepo(_state(request).conn).delete_source(source_id)
    return {"status": "deleted"}


@router.post("/news/sync")
async def news_sync(request: Request) -> dict[str, Any]:
    # Run blocking RSS I/O off the event loop so library JobQueue can keep scheduling.
    results = await asyncio.to_thread(sync_all, _state(request).conn)
    return {
        "results": [
            {
                "source_url": r.source_url,
                "fetched": r.fetched,
                "inserted": r.inserted,
                "error": r.error,
            }
            for r in results
        ]
    }


@router.get("/news/brief")
async def news_brief(
    request: Request,
    limit: int = Query(25, ge=5, le=50),
) -> dict[str, Any]:
    return await asyncio.to_thread(build_brief, _state(request).conn, limit=limit)


@router.get("/news/articles/{article_id}")
async def get_news_article(article_id: str, request: Request) -> dict[str, Any]:
    article = NewsStore(_state(request).conn).get(article_id)
    if not article:
        raise HTTPException(404, "Article not found")
    return article


class NewsReadRequest(BaseModel):
    force_refetch: bool = False
    skim_only: bool = False


@router.post("/news/articles/{article_id}/read")
async def news_article_read(
    article_id: str, request: Request, body: NewsReadRequest | None = None
) -> dict[str, Any]:
    state = _state(request)
    article = NewsStore(state.conn).get(article_id)
    if not article:
        raise HTTPException(404, "Article not found")

    force = bool(body.force_refetch) if body else False
    skim_only = bool(body.skim_only) if body else False
    # Reuse cached summary unless force refetch.
    if (
        not force
        and article.get("summary_status") == "ready"
        and article.get("summary_markdown")
    ):
        body_text = "" if skim_only else load_cached_body(article)
        return {
            "article": article,
            "summary_markdown": article["summary_markdown"],
            "warnings": [],
            "error": "",
            "body_complete": True,
            "body_text": body_text,
        }

    cache_dir = state.settings.data_dir / "news_cache"
    article_title = article.get("title") or article_id
    cancel_event = asyncio.Event()
    record = register_article_task(
        state.task_registry,
        kind="news_read",
        article_id=article_id,
        subject_label=article_title,
        detail="资讯精读",
        profile="summarize",
        cancellable=True,
        cancel_fn=cancel_event.set,
    )
    # News must not pause library summarize/translate (independent workflows).
    try:
        result = await track_async_task(
            state.task_registry,
            record,
            read_article(
                state.conn,
                state.router,
                article_id,
                cache_dir=cache_dir,
                force_refetch=force,
                use_llm=True,
                prompts=_prompts(state),
                target_language=state.settings.target_language,
            ),
            router_resource=lambda: state.router.last_resource_id,
        )
    except Exception:
        if cancel_event.is_set():
            raise HTTPException(499, "Task cancelled")
        raise

    if result.error and not result.summary_markdown:
        raise HTTPException(502, result.error)
    body_text = "" if skim_only else result.body_text
    return {
        "article": result.article,
        "summary_markdown": result.summary_markdown,
        "warnings": result.warnings,
        "error": result.error,
        "body_complete": result.body_complete,
        "body_text": body_text,
    }


@router.post("/news/articles/{article_id}/chat")
async def news_article_chat(article_id: str, body: NewsChatRequest, request: Request):
    state = _state(request)
    article = NewsStore(state.conn).get(article_id)
    if not article:
        raise HTTPException(404, "Article not found")

    if body.stream:
        return await news_article_chat_stream(article_id, body, request)

    article_title = article.get("title") or article_id
    record = register_article_task(
        state.task_registry,
        kind="news_chat",
        article_id=article_id,
        subject_label=article_title,
        detail="资讯深聊",
        profile="chat",
    )
    return await track_async_task(
        state.task_registry,
        record,
        chat_with_article(
            state.router,
            NewsChatRepo(state.conn),
            article=article,
            message=body.message,
            quote=body.quote,
            web_search_provider=state.settings.web_search_provider,
            tavily_api_key=state.settings.tavily_api_key,
            web_search_enabled=state.settings.web_search_enabled,
            prompts=_prompts(state),
        ),
        router_resource=lambda: state.router.last_resource_id,
    )


async def news_article_chat_stream(
    article_id: str, body: NewsChatRequest, request: Request
) -> StreamingResponse:
    state = _state(request)
    article = NewsStore(state.conn).get(article_id)
    if not article:
        raise HTTPException(404, "Article not found")

    article_title = article.get("title") or article_id
    cancel_event = asyncio.Event()
    record = register_article_task(
        state.task_registry,
        kind="news_chat",
        article_id=article_id,
        subject_label=article_title,
        detail="资讯深聊",
        profile="chat",
        cancellable=True,
        cancel_fn=cancel_event.set,
    )

    async def stream():
        try:
            event_stream = stream_chat_with_article(
                state.router,
                NewsChatRepo(state.conn),
                article=article,
                message=body.message,
                quote=body.quote,
                web_search_provider=state.settings.web_search_provider,
                tavily_api_key=state.settings.tavily_api_key,
                web_search_enabled=state.settings.web_search_enabled,
                prompts=_prompts(state),
            )
            async for event in track_stream_events(
                state.task_registry,
                record,
                event_stream,
                cancel_event=cancel_event,
                router_resource=lambda: state.router.last_resource_id,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': f'深聊失败：{exc}'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
