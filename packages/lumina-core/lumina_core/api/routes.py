"""FastAPI routes."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from lumina_core.app_state import AppState
from lumina_core.chat.news_service import chat_with_article, stream_chat_with_article
from lumina_core.chat.service import chat_with_book, stream_chat_with_book
from lumina_core.config import ModelsConfig, Settings
from lumina_core.db.repos import BookRepo, ChatRepo, NewsChatRepo, NoteRepo, SegmentRepo
from lumina_core.export.markdown import export_book_markdown
from lumina_core.ingest.loader import (
    author_from_metadata,
    build_segments,
    copy_to_library,
    detect_format,
    file_hash,
    load_document,
    title_from_path,
    validate_import,
)
from lumina_core.news.brief import build_brief
from lumina_core.news.store import NewsSourceRepo, NewsStore
from lumina_core.news.sync import sync_all
from lumina_core.search.fts import index_book, index_note, search
from lumina_core.ollama_setup import check_ollama_status
from lumina_core.settings_store import models_to_dict, save_settings

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


class ExportRequest(BaseModel):
    include_notes: bool = False


class SettingsUpdate(BaseModel):
    target_language: str | None = None
    web_search_enabled: bool | None = None
    models: ModelsConfig | None = None


class NoteCreate(BaseModel):
    book_id: str
    content: str
    segment_id: str | None = None
    quote: str | None = None
    type: str = "manual"


class NewsSourceCreate(BaseModel):
    url: str
    title: str = ""


def _state(request: Request) -> AppState:
    return request.app.state.lumina  # type: ignore[attr-defined]


def _wire_job_events(state: AppState) -> None:
    async def _on_event(bid: str, payload: dict[str, Any]) -> None:
        for q in state.event_subscribers.get(bid, []):
            await q.put(payload)

    state.job_queue.set_event_callback(_on_event)


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

        digest = file_hash(src)
        existing = books_repo.find_by_hash(digest)
        if existing and not body.overwrite:
            raise HTTPException(
                409,
                detail={"existing_book_id": existing["id"], "title": existing["title"]},
            )
        if existing and body.overwrite:
            books_repo.delete(existing["id"])

        fmt = detect_format(src)
        if fmt not in SUPPORTED_FORMATS:
            raise HTTPException(400, f"Unsupported format: {fmt}")

        try:
            book_id = str(uuid.uuid4())
            dest = copy_to_library(src, state.books_dir, book_id)
            text, metadata = load_document(dest, fmt)
            if not text.strip():
                raise HTTPException(400, "No extractable text in document")

            segments = build_segments(book_id, text)
            book = books_repo.insert(
                id=book_id,
                title=title_from_path(src, metadata),
                author=author_from_metadata(metadata),
                format=fmt,
                file_path=str(dest),
                file_hash=digest,
                segment_count=len(segments),
                status="processing",
            )
            SegmentRepo(state.conn).insert_many(segments)
            index_book(state.conn, book)
            await state.job_queue.enqueue_book_prefetch(book_id)
            results.append({"book_id": book_id, "status": "processing", "title": book["title"]})
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(400, f"Import failed: {e}") from e

    return {"books": results}


@router.post("/books/{book_id}/import/overwrite")
async def overwrite_book(book_id: str, body: ImportRequest, request: Request) -> dict[str, Any]:
    body.overwrite = True
    return await import_books(body, request)


@router.get("/books")
async def list_books(request: Request) -> dict[str, Any]:
    books = BookRepo(_state(request).conn).list_books()
    return {"books": books}


@router.get("/books/{book_id}")
async def get_book(book_id: str, request: Request) -> dict[str, Any]:
    book = BookRepo(_state(request).conn).get(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    return book


@router.get("/books/{book_id}/segments")
async def list_segments(book_id: str, request: Request) -> dict[str, Any]:
    segments = SegmentRepo(_state(request).conn).list_for_book(book_id)
    return {"segments": segments}


@router.get("/books/{book_id}/segments/{idx}")
async def get_segment(book_id: str, idx: int, request: Request) -> dict[str, Any]:
    seg = SegmentRepo(_state(request).conn).get_by_index(book_id, idx)
    if not seg:
        raise HTTPException(404, "Segment not found")
    return seg


@router.post("/books/{book_id}/open")
async def open_book(book_id: str, request: Request) -> dict[str, str]:
    book = BookRepo(_state(request).conn).get(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    BookRepo(_state(request).conn).update(book_id, status="reading")
    return {"status": "opened"}


@router.post("/books/{book_id}/segments/{idx}/retry")
async def retry_segment(book_id: str, idx: int, request: Request) -> dict[str, str]:
    state = _state(request)
    seg = SegmentRepo(state.conn).get_by_index(book_id, idx)
    if not seg:
        raise HTTPException(404, "Segment not found")
    SegmentRepo(state.conn).set_status(seg["id"], "pending", retry_count=0)
    await state.job_queue.enqueue_summarize(book_id, seg["id"], idx, high=True)
    return {"status": "queued"}


@router.get("/books/{book_id}/events")
async def book_events(book_id: str, request: Request) -> StreamingResponse:
    state = _state(request)
    queue: asyncio.Queue = asyncio.Queue()
    state.event_subscribers.setdefault(book_id, []).append(queue)

    async def stream():
        try:
            segments = SegmentRepo(state.conn).list_for_book(book_id)
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

    state.job_queue.pause_ollama()
    try:
        result = await chat_with_book(
            state.router,
            ChatRepo(state.conn),
            SegmentRepo(state.conn),
            book=book,
            message=body.message,
            current_segment_idx=body.segment_index,
            web_enabled=state.settings.web_search_enabled,
            quote=body.quote,
        )
    finally:
        state.job_queue.resume_ollama()
    return result


async def book_chat_stream(book_id: str, body: ChatRequest, request: Request) -> StreamingResponse:
    state = _state(request)
    book = BookRepo(state.conn).get(book_id)
    if not book:
        raise HTTPException(404, "Book not found")

    async def stream():
        state.job_queue.pause_ollama()
        try:
            async for event in stream_chat_with_book(
                state.router,
                ChatRepo(state.conn),
                SegmentRepo(state.conn),
                book=book,
                message=body.message,
                current_segment_idx=body.segment_index,
                web_enabled=state.settings.web_search_enabled,
                quote=body.quote,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            state.job_queue.resume_ollama()

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/books/{book_id}/export")
async def export_book(book_id: str, body: ExportRequest, request: Request) -> PlainTextResponse:
    state = _state(request)
    book = BookRepo(state.conn).get(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    segments = SegmentRepo(state.conn).list_for_book(book_id)
    md = export_book_markdown(book, segments, include_notes=body.include_notes)
    filename = f"{book.get('title', 'book')}-summary.md"
    return PlainTextResponse(
        md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/settings")
async def get_settings(request: Request) -> dict[str, Any]:
    state = _state(request)
    return {
        "target_language": state.settings.target_language,
        "web_search_enabled": state.settings.web_search_enabled,
        "models": models_to_dict(state.models),
    }


@router.put("/settings")
async def update_settings(body: SettingsUpdate, request: Request) -> dict[str, Any]:
    state = _state(request)
    if body.target_language is not None:
        state.settings.target_language = body.target_language
        state.job_queue.target_language = body.target_language
    if body.web_search_enabled is not None:
        state.settings.web_search_enabled = body.web_search_enabled
    if body.models is not None:
        state.models = body.models
        state.router = __import__(
            "lumina_core.models.router", fromlist=["ProfileModelRouter"]
        ).ProfileModelRouter(body.models)
        state.job_queue.router = state.router
    save_settings(state.settings)
    return await get_settings(request)


@router.get("/settings/ollama/status")
async def ollama_status(request: Request) -> dict[str, Any]:
    state = _state(request)
    status = await check_ollama_status(
        state.models.summarize.base_url,
        state.models.summarize.model,
    )
    return status.__dict__


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
async def list_notes(book_id: str, request: Request) -> dict[str, Any]:
    notes = NoteRepo(_state(request).conn).list_for_book(book_id)
    return {"notes": notes}


@router.get("/search")
async def global_search(q: str, request: Request) -> dict[str, Any]:
    results = search(_state(request).conn, q)
    return {"results": results}


# --- News lite ---


@router.get("/news/sources")
async def list_news_sources(request: Request) -> dict[str, Any]:
    sources = NewsSourceRepo(_state(request).conn).list_sources()
    return {"sources": sources}


@router.post("/news/sources")
async def add_news_source(body: NewsSourceCreate, request: Request) -> dict[str, Any]:
    source = NewsSourceRepo(_state(request).conn).add_source(body.url, body.title)
    return source


@router.delete("/news/sources/{source_id}")
async def delete_news_source(source_id: str, request: Request) -> dict[str, str]:
    NewsSourceRepo(_state(request).conn).delete_source(source_id)
    return {"status": "deleted"}


@router.post("/news/sync")
async def news_sync(request: Request) -> dict[str, Any]:
    results = sync_all(_state(request).conn)
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
async def news_brief(request: Request) -> dict[str, Any]:
    return build_brief(_state(request).conn)


@router.get("/news/articles/{article_id}")
async def get_news_article(article_id: str, request: Request) -> dict[str, Any]:
    article = NewsStore(_state(request).conn).get(article_id)
    if not article:
        raise HTTPException(404, "Article not found")
    return article


@router.post("/news/articles/{article_id}/chat")
async def news_article_chat(article_id: str, body: NewsChatRequest, request: Request):
    state = _state(request)
    article = NewsStore(state.conn).get(article_id)
    if not article:
        raise HTTPException(404, "Article not found")

    if body.stream:
        return await news_article_chat_stream(article_id, body, request)

    state.job_queue.pause_ollama()
    try:
        result = await chat_with_article(
            state.router,
            NewsChatRepo(state.conn),
            article=article,
            message=body.message,
            web_enabled=state.settings.web_search_enabled,
        )
    finally:
        state.job_queue.resume_ollama()
    return result


async def news_article_chat_stream(
    article_id: str, body: NewsChatRequest, request: Request
) -> StreamingResponse:
    state = _state(request)
    article = NewsStore(state.conn).get(article_id)
    if not article:
        raise HTTPException(404, "Article not found")

    async def stream():
        state.job_queue.pause_ollama()
        try:
            async for event in stream_chat_with_article(
                state.router,
                NewsChatRepo(state.conn),
                article=article,
                message=body.message,
                web_enabled=state.settings.web_search_enabled,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            state.job_queue.resume_ollama()

    return StreamingResponse(stream(), media_type="text/event-stream")
