"""FastAPI routes."""

from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from lumina_core.app_state import AppState, default_rss_sources
from lumina_core.chat.news_service import chat_with_article, stream_chat_with_article
from lumina_core.chat.service import chat_with_book, stream_chat_with_book
from lumina_core.config import ModelsConfig, PromptsConfig, Settings
from lumina_core.classify.book import BOOK_CATEGORIES
from lumina_core.classify.tasks import run_classify_book, validate_manual_category
from lumina_core.db.repos import BookRepo, ChatRepo, NewsChatRepo, NoteRepo, SegmentRepo
from lumina_core.export.markdown import content_disposition_attachment, export_book_markdown
from lumina_core.ingest.loader import (
    copy_to_library,
    detect_format,
    file_hash,
    title_from_path,
    validate_import,
)
from lumina_core.jobs.ingest import run_ingest_job
from lumina_core.news.brief import build_brief
from lumina_core.news.read import load_cached_body, read_article
from lumina_core.news.store import NewsSourceRepo, NewsStore
from lumina_core.news.sync import sync_all
from lumina_core.search.fts import index_book, index_note, search
from lumina_core.resource_probe import probe_resource
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
    merge_prompts,
    merge_tavily_api_key,
    models_to_dict,
    normalize_web_search_provider,
    save_models,
    save_settings,
    settings_public_dict,
)

router = APIRouter()

SUPPORTED_FORMATS = {"txt", "pdf", "epub", "mobi"}


class ImportRequest(BaseModel):
    paths: list[str]
    overwrite: bool = False


class ChatRequest(BaseModel):
    message: str
    segment_index: int = 0
    stream: bool = False
    quote: str | None = None


class NewsChatRequest(BaseModel):
    message: str
    stream: bool = False
    quote: str | None = None


class ExportRequest(BaseModel):
    include_notes: bool = False


class RetrySegmentsRequest(BaseModel):
    indices: list[int]


class SummarizeBatchRequest(BaseModel):
    book_ids: list[str] = []


class ReadingProgressUpdate(BaseModel):
    segment_index: int


class BookPatchUpdate(BaseModel):
    is_favorite: bool | None = None
    category: str | None = None
    title: str | None = None


class SettingsUpdate(BaseModel):
    target_language: str | None = None
    web_search_provider: str | None = None
    tavily_api_key: str | None = None
    debug_mode: bool | None = None
    auto_start_summary: bool | None = None
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
    await state.job_queue.stop_book(book_id)
    BookRepo(state.conn).delete(book_id)
    book_dir = state.books_dir / book_id
    if book_dir.exists():
        await asyncio.to_thread(shutil.rmtree, book_dir)


def _wire_job_events(state: AppState) -> None:
    async def _on_event(bid: str, payload: dict[str, Any]) -> None:
        for q in state.event_subscribers.get(bid, []):
            await q.put(payload)

    state.job_queue.set_event_callback(_on_event)


async def _queue_segment_retry(
    state: AppState, book_id: str, idx: int, *, seg: dict[str, Any] | None = None
) -> None:
    if seg is None:
        seg = SegmentRepo(state.conn).get_by_index(book_id, idx)
        if not seg:
            raise HTTPException(404, "Segment not found")
    state.job_queue.unpause_book(book_id)
    SegmentRepo(state.conn).set_status(seg["id"], "pending", retry_count=0)
    await state.job_queue.enqueue_summarize(book_id, seg["id"], idx, high=True)


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


def book_public_dict(
    row: dict[str, Any],
    *,
    conn: sqlite3.Connection | None = None,
    summarize_active: dict[str, Any] | None = None,
    summarize_state: str | None = None,
    summarize_queued_count: int | None = None,
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

    if conn is not None and out.get("id"):
        progress = BookRepo(conn).summary_progress(out["id"])
        out.update(progress)
    else:
        out.setdefault("summary_ready_count", 0)
        out.setdefault("summary_total_count", out.get("segment_count") or 0)

    if summarize_active is not None:
        out["summarize_active"] = summarize_active

    if summarize_state is not None and row.get("status") != "processing":
        out["summarize_state"] = summarize_state
        out["summarize_queued_count"] = summarize_queued_count or 0

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


def _schedule_ingest(
    state: AppState,
    *,
    book_id: str,
    dest: Path,
    fmt: str,
    src: Path,
) -> None:
    async def _run() -> None:
        await run_ingest_job(
            book_id=book_id,
            dest=dest,
            fmt=fmt,
            src=src,
            conn=state.conn,
            models=state.models,
            target_language=state.settings.target_language,
            job_queue=state.job_queue,
            emit=lambda book_id, payload: _emit_book_event(state, book_id, payload),
            schedule_classify=lambda bid: _schedule_classify(state, bid),
        )

    asyncio.create_task(_run())


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


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
        books = BookRepo(conn).list_books(filter=filter, sort=sort)
        active_by_book = state.job_queue.summarize_active_by_book()
        state_by_book = state.job_queue.summarize_state_by_book()
        result = [
            book_public_dict(
                b,
                conn=conn,
                summarize_active=active_by_book.get(b["id"]),
                summarize_state=state_by_book.get(b["id"], {}).get(
                    "summarize_state"
                ),
                summarize_queued_count=state_by_book.get(b["id"], {}).get(
                    "summarize_queued_count", 0
                ),
            )
            for b in books
        ]
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

    if not updates:
        return _book_public_with_queue(state, book)

    repo.update(book_id, **updates)
    updated = repo.get(book_id)
    if updated and "title" in updates:
        index_book(state.conn, updated)
    return _book_public_with_queue(state, updated)  # type: ignore[arg-type]


@router.delete("/books/{book_id}")
async def delete_book(book_id: str, request: Request) -> dict[str, str]:
    state = _state(request)
    book = BookRepo(state.conn).get(book_id)
    if not book:
        raise HTTPException(404, "Book not found")

    await _purge_book(state, book_id)
    return {"status": "deleted"}


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
    )


@router.get("/books/{book_id}/segments")
async def list_segments(
    book_id: str,
    request: Request,
    include_summary: bool = Query(False),
) -> dict[str, Any]:
    # Slim meta — raw_text/translation/summary_json via GET .../segments/{idx} (never-freeze).
    repo = SegmentRepo(_state(request).conn)

    def _list_meta() -> list[dict[str, Any]]:
        try:
            return repo.list_for_book(
                book_id, include_body=False, include_summary=include_summary
            )
        except sqlite3.OperationalError as e:
            _raise_on_db_schema_error(e)
            raise  # pragma: no cover

    segments = await asyncio.to_thread(_list_meta)
    return {"segments": segments}


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


@router.post("/books/{book_id}/open")
async def open_book(book_id: str, request: Request) -> dict[str, Any]:
    state = _state(request)
    book = BookRepo(state.conn).get(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    now = _now_iso()
    fields: dict[str, Any] = {"last_opened_at": now}
    if book.get("status") == "unread":
        fields["status"] = "reading"
    try:
        BookRepo(state.conn).update(book_id, **fields)
    except sqlite3.OperationalError as e:
        raise HTTPException(503, _SCHEMA_STALE_DETAIL) from e
    _wire_job_events(state)
    if state.job_queue.auto_start_summary:
        await state.job_queue.enqueue_book_prefetch(book_id)
    return {
        "status": "opened",
        "current_segment_index": book.get("current_segment_index") or 0,
    }


@router.patch("/books/{book_id}/reading-progress")
async def update_reading_progress(
    book_id: str, body: ReadingProgressUpdate, request: Request
) -> dict[str, int]:
    book = BookRepo(_state(request).conn).get(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    segment_count = book.get("segment_count") or 0
    if segment_count > 0 and not (0 <= body.segment_index < segment_count):
        raise HTTPException(
            400,
            f"segment_index must be between 0 and {segment_count - 1}",
        )
    BookRepo(_state(request).conn).update(
        book_id, current_segment_index=body.segment_index
    )
    return {"current_segment_index": body.segment_index}


@router.get("/books/summarize/overview")
async def summarize_overview(request: Request) -> dict[str, Any]:
    state = _state(request)
    return state.job_queue.summarize_overview()


@router.post("/books/summarize/start")
async def start_summarize_batch(
    request: Request, body: SummarizeBatchRequest | None = None
) -> dict[str, Any]:
    state = _state(request)
    _wire_job_events(state)
    book_ids = body.book_ids if body else []
    if not book_ids:
        await state.job_queue.start_all()
        return {"status": "started", "scope": "all", "book_ids": [], "affected_count": 0}

    repo = BookRepo(state.conn)
    affected: list[str] = []
    skipped: list[str] = []
    for book_id in book_ids:
        if not repo.get(book_id):
            skipped.append(book_id)
            continue
        await state.job_queue.start_book(book_id)
        affected.append(book_id)
    return {
        "status": "started",
        "scope": "batch",
        "book_ids": affected,
        "affected_count": len(affected),
        "skipped": skipped,
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
        if not repo.get(book_id):
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
async def start_summarize_book(book_id: str, request: Request) -> dict[str, str]:
    state = _state(request)
    book = BookRepo(state.conn).get(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    _wire_job_events(state)
    await state.job_queue.start_book(book_id)
    return {"status": "started", "scope": "book", "book_id": book_id}


@router.post("/books/{book_id}/summarize/stop")
async def stop_summarize_book(book_id: str, request: Request) -> dict[str, str]:
    state = _state(request)
    book = BookRepo(state.conn).get(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    _wire_job_events(state)
    await state.job_queue.stop_book(book_id)
    return {"status": "stopped", "scope": "book", "book_id": book_id}


@router.post("/books/{book_id}/segments/{idx}/retry")
async def retry_segment(book_id: str, idx: int, request: Request) -> dict[str, str]:
    state = _state(request)
    await _queue_segment_retry(state, book_id, idx)
    return {"status": "queued"}


@router.post("/books/{book_id}/segments/retry")
async def retry_segments(
    book_id: str, body: RetrySegmentsRequest, request: Request
) -> dict[str, int | str]:
    state = _state(request)
    book = BookRepo(state.conn).get(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    indices = sorted(set(body.indices))
    if not indices:
        raise HTTPException(400, "indices must not be empty")
    seg_repo = SegmentRepo(state.conn)
    segments: list[tuple[int, dict[str, Any]]] = []
    for idx in indices:
        seg = seg_repo.get_by_index(book_id, idx)
        if not seg:
            raise HTTPException(400, f"Segment not found: {idx}")
        segments.append((idx, seg))
    _wire_job_events(state)
    for idx, seg in segments:
        await _queue_segment_retry(state, book_id, idx, seg=seg)
    return {"status": "queued", "count": len(segments)}


@router.post("/books/{book_id}/summarize/regenerate")
async def regenerate_book_summaries(
    book_id: str, request: Request
) -> dict[str, int | str]:
    state = _state(request)
    book = BookRepo(state.conn).get(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    _wire_job_events(state)
    if book.get("status") == "summarized":
        BookRepo(state.conn).update(book_id, status="reading")
    count = await state.job_queue.enqueue_book_regenerate(book_id)
    return {"status": "queued", "count": count}


@router.get("/books/{book_id}/events")
async def book_events(book_id: str, request: Request) -> StreamingResponse:
    state = _state(request)
    queue: asyncio.Queue = asyncio.Queue()
    state.event_subscribers.setdefault(book_id, []).append(queue)

    async def stream():
        try:
            segments = await asyncio.to_thread(
                SegmentRepo(state.conn).list_for_book,
                book_id,
                include_body=False,
            )
            yield f"data: {json.dumps({'type': 'snapshot', 'segments': [{'idx': s['idx'], 'summary_status': s['summary_status'], 'label': s.get('label')} for s in segments]}, ensure_ascii=False)}\n\n"
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


@router.post("/books/{book_id}/chat")
async def book_chat(book_id: str, body: ChatRequest, request: Request):
    state = _state(request)
    book = BookRepo(state.conn).get(book_id)
    if not book:
        raise HTTPException(404, "Book not found")

    if body.stream:
        return await book_chat_stream(book_id, body, request)

    title = book.get("title") or book_id
    segment_detail = f"深聊 · 段 {body.segment_index + 1}"
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
                web_search_provider=state.settings.web_search_provider,
                tavily_api_key=state.settings.tavily_api_key,
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

    title = book.get("title") or book_id
    segment_detail = f"深聊 · 段 {body.segment_index + 1}"
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
                web_search_provider=state.settings.web_search_provider,
                tavily_api_key=state.settings.tavily_api_key,
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
        notes = (
            NoteRepo(state.conn).list_for_book(book_id) if body.include_notes else None
        )
        return export_book_markdown(
            book,
            segments,
            include_notes=body.include_notes,
            notes=notes,
        )

    md = await asyncio.to_thread(_build_markdown)
    filename = f"{book.get('title', 'book')}-summary.md"
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
    if "tavily_api_key" in body.model_fields_set:
        state.settings.tavily_api_key = merge_tavily_api_key(
            body.tavily_api_key, state.settings.tavily_api_key
        )
    if body.debug_mode is not None:
        state.settings.debug_mode = body.debug_mode
    if body.auto_start_summary is not None:
        state.settings.auto_start_summary = body.auto_start_summary
        state.job_queue.auto_start_summary = body.auto_start_summary
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


@router.get("/settings/resources/{resource_id}/status")
async def resource_status(resource_id: str, request: Request) -> dict[str, Any]:
    state = _state(request)
    resource = state.models.resource_by_id(resource_id)
    if resource is None:
        raise HTTPException(404, "Resource not found")
    status = await probe_resource(resource)
    return status.to_dict()


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
async def shutdown() -> dict[str, str]:
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
    note = NoteRepo(state.conn).create(
        book_id=body.book_id,
        content=body.content,
        note_type=body.type,
        segment_id=body.segment_id,
        quote=body.quote,
    )
    index_note(state.conn, book, note)
    return note


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
    sources = NewsSourceRepo(_state(request).conn).list_sources()
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
