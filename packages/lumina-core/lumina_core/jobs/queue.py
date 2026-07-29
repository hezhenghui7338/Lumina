"""Background job queue with priority and chat preemption."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine

import sqlite3

from lumina_core.config import (
    SUMMARY_JOB_MAX_RETRIES,
    SUMMARY_SEGMENT_TIMEOUT_SECONDS,
)
from lumina_core.db.repos import BookRepo, SegmentRepo
from lumina_core.models.router import ProfileModelRouter
from lumina_core.summarize.segment import (
    segment_ready_event_payload,
    summarize_segment,
    summary_to_json,
)
from lumina_core.translate.language import book_needs_translation, infer_language
from lumina_core.translate.translator import translate_segment

logger = logging.getLogger(__name__)


class JobKind(str, Enum):
    SUMMARIZE = "summarize"
    TRANSLATE = "translate"


@dataclass(order=True)
class JobItem:
    priority: int
    book_id: str = field(compare=False)
    segment_id: str = field(compare=False)
    segment_idx: int = field(compare=False)
    kind: JobKind = field(compare=False)
    retry_count: int = field(default=0, compare=False)


EventCallback = Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]


def _job_key(item: JobItem) -> str:
    return f"{item.book_id}:{item.segment_id}:{item.kind.value}"


class JobQueue:
    def __init__(
        self,
        conn: sqlite3.Connection,
        router: ProfileModelRouter,
        *,
        target_language: str = "zh-CN",
    ) -> None:
        self.conn = conn
        self.router = router
        self.target_language = target_language
        self._queue: asyncio.PriorityQueue[JobItem] = asyncio.PriorityQueue()
        self._paused = asyncio.Event()
        self._paused.set()
        self._worker_count = 0
        self._event_callback: EventCallback | None = None
        self._books_repo = BookRepo(conn)
        self._segments_repo = SegmentRepo(conn)
        # User-controlled summarize pause (separate from chat pause_ollama)
        self._user_paused_all = False
        self._user_paused_books: set[str] = set()
        self._active: dict[str, JobItem] = {}
        self._cancelled: set[str] = set()

    def set_event_callback(self, cb: EventCallback) -> None:
        self._event_callback = cb

    async def emit(self, book_id: str, payload: dict[str, Any]) -> None:
        if self._event_callback:
            await self._event_callback(book_id, payload)

    def _summary_progress(self, book_id: str) -> dict[str, int]:
        return self._books_repo.summary_progress(book_id)

    async def _emit_segment_event(self, book_id: str, payload: dict[str, Any]) -> None:
        payload.update(self._summary_progress(book_id))
        await self.emit(book_id, payload)

    def refresh_workers(self) -> None:
        """Scale workers to match summarize profile concurrency."""
        self.ensure_workers()

    def ensure_workers(self) -> None:
        """Start enough workers to match summarize profile concurrency."""
        target = self._worker_target()
        while self._worker_count < target:
            asyncio.create_task(self._worker())
            self._worker_count += 1

    def _worker_target(self) -> int:
        return self.router.models.max_concurrency_for_profile("summarize")

    def pause_ollama(self) -> None:
        self._paused.clear()

    def resume_ollama(self) -> None:
        self._paused.set()

    def is_user_paused(self, book_id: str) -> bool:
        if book_id in self._user_paused_books:
            return True
        return self._user_paused_all

    def unpause_book(self, book_id: str) -> None:
        """Clear per-book pause; if global pause is on, clear it so this book can run."""
        self._user_paused_books.discard(book_id)
        if self._user_paused_all:
            self._user_paused_all = False

    async def enqueue_summarize(
        self, book_id: str, segment_id: str, segment_idx: int, *, high: bool = False
    ) -> None:
        if self.is_user_paused(book_id):
            return
        priority = 0 if high else segment_idx + 1
        await self._queue.put(
            JobItem(
                priority=priority,
                book_id=book_id,
                segment_id=segment_id,
                segment_idx=segment_idx,
                kind=JobKind.SUMMARIZE,
            )
        )
        self.ensure_workers()

    def _book_needs_translation(self, book_id: str) -> bool:
        book = self._books_repo.get(book_id)
        if not book:
            return False
        text_sample: str | None = None
        if not book.get("language"):
            segments = self._segments_repo.list_for_book(book_id, include_body=True)
            if segments:
                text_sample = (segments[0].get("raw_text") or "")[:2000]
        return book_needs_translation(
            book_language=book.get("language"),
            book_target_language=book.get("target_language"),
            global_target_language=self.target_language,
            text_sample=text_sample,
        )

    async def enqueue_translate(
        self, book_id: str, segment_id: str, segment_idx: int
    ) -> None:
        if self.is_user_paused(book_id):
            return
        if not self._book_needs_translation(book_id):
            return
        await self._queue.put(
            JobItem(
                priority=1000 + segment_idx,
                book_id=book_id,
                segment_id=segment_id,
                segment_idx=segment_idx,
                kind=JobKind.TRANSLATE,
            )
        )
        self.ensure_workers()

    async def enqueue_book_prefetch(self, book_id: str) -> None:
        if self.is_user_paused(book_id):
            return
        await self._recover_stale_running(book_id)
        segments = self._segments_repo.list_for_book(book_id)
        for seg in segments:
            if seg["summary_status"] in ("pending", "failed", "error"):
                await self.enqueue_summarize(
                    book_id, seg["id"], seg["idx"], high=(seg["idx"] == 0)
                )

    async def recover_on_startup(self) -> None:
        """Reset orphan running segments and resume prefetch after Sidecar restart."""
        for book in self._books_repo.list_books():
            self._books_repo.maybe_mark_summarized(book["id"])
            await self.enqueue_book_prefetch(book["id"])
        self.ensure_workers()

    async def enqueue_book_regenerate(self, book_id: str) -> int:
        """Force re-summarize every segment (including ready)."""
        self.unpause_book(book_id)
        segments = self._segments_repo.list_for_book(book_id)
        for seg in segments:
            self._segments_repo.set_status(seg["id"], "pending", retry_count=0)
            await self.enqueue_summarize(
                book_id, seg["id"], seg["idx"], high=True
            )
        return len(segments)

    async def stop_book(self, book_id: str) -> None:
        self._user_paused_books.add(book_id)
        await self._filter_queue(lambda item: item.book_id != book_id)
        await self._cancel_active(lambda item: item.book_id == book_id)
        await self._reset_running_segments(book_id)
        await self.emit(
            book_id,
            {"type": "summarize_paused", "scope": "book", "book_id": book_id},
        )

    async def stop_all(self) -> None:
        self._user_paused_all = True
        self._user_paused_books.clear()
        await self._filter_queue(lambda _item: False)
        await self._cancel_active(lambda _item: True)
        books = self._books_repo.list_books()
        for book in books:
            await self._reset_running_segments(book["id"])
            await self.emit(
                book["id"],
                {"type": "summarize_paused", "scope": "all", "book_id": book["id"]},
            )

    async def start_book(self, book_id: str) -> None:
        self.unpause_book(book_id)
        await self._reset_segments_for_user_resume(book_id)
        await self.enqueue_book_prefetch(book_id)
        await self.emit(
            book_id,
            {"type": "summarize_resumed", "scope": "book", "book_id": book_id},
        )

    async def start_all(self) -> None:
        self._user_paused_all = False
        self._user_paused_books.clear()
        books = self._books_repo.list_books()
        for book in books:
            await self._reset_segments_for_user_resume(book["id"])
            await self.enqueue_book_prefetch(book["id"])
            await self.emit(
                book["id"],
                {"type": "summarize_resumed", "scope": "all", "book_id": book["id"]},
            )

    async def _filter_queue(self, keep: Callable[[JobItem], bool]) -> None:
        kept: list[JobItem] = []
        while True:
            try:
                item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            self._queue.task_done()
            if keep(item):
                kept.append(item)
        for item in kept:
            await self._queue.put(item)

    async def _cancel_active(self, match: Callable[[JobItem], bool]) -> None:
        for key, item in list(self._active.items()):
            if match(item):
                self._cancelled.add(key)

    async def _reset_running_segments(self, book_id: str) -> None:
        for seg in self._segments_repo.list_for_book(book_id):
            if seg["summary_status"] == "running":
                self._segments_repo.set_status(seg["id"], "pending")
                await self._emit_segment_event(
                    book_id,
                    {
                        "type": "segment_status",
                        "idx": seg["idx"],
                        "status": "pending",
                    },
                )

    async def _reset_segments_for_user_resume(self, book_id: str) -> None:
        """Reset failed/error segments so start_summarize gets a fresh retry budget."""
        for seg in self._segments_repo.list_for_book(book_id):
            if seg["summary_status"] not in ("failed", "error"):
                continue
            self._segments_repo.set_status(seg["id"], "pending", retry_count=0)
            await self._emit_segment_event(
                book_id,
                {
                    "type": "segment_status",
                    "idx": seg["idx"],
                    "status": "pending",
                },
            )

    async def _recover_stale_running(self, book_id: str) -> None:
        """Reset running segments with no active worker (crash/restart orphans)."""
        for seg in self._segments_repo.list_for_book(book_id):
            if seg["summary_status"] != "running":
                continue
            key = f"{book_id}:{seg['id']}:{JobKind.SUMMARIZE.value}"
            if key in self._active:
                continue
            self._segments_repo.set_status(seg["id"], "pending")
            await self._emit_segment_event(
                book_id,
                {
                    "type": "segment_status",
                    "idx": seg["idx"],
                    "status": "pending",
                },
            )

    def _was_cancelled(self, item: JobItem) -> bool:
        return _job_key(item) in self._cancelled or self.is_user_paused(item.book_id)

    async def _worker(self) -> None:
        while True:
            await self._paused.wait()
            item = await self._queue.get()
            key = _job_key(item)
            try:
                if self.is_user_paused(item.book_id):
                    continue
                self._active[key] = item
                try:
                    if item.kind == JobKind.SUMMARIZE:
                        await self._run_summarize(item)
                    elif item.kind == JobKind.TRANSLATE:
                        await self._run_translate(item)
                finally:
                    self._active.pop(key, None)
                    self._cancelled.discard(key)
            except Exception:
                logger.exception("Job failed: %s", item)
            finally:
                self._queue.task_done()

    async def _run_summarize(self, item: JobItem) -> None:
        seg = self._segments_repo.get_by_index(item.book_id, item.segment_idx)
        if not seg:
            return
        if self._was_cancelled(item):
            return
        self._segments_repo.set_status(seg["id"], "running")
        await self._emit_segment_event(
            item.book_id,
            {"type": "segment_status", "idx": item.segment_idx, "status": "running"},
        )
        try:
            summary = await asyncio.wait_for(
                summarize_segment(
                    self.router,
                    raw_text=seg["raw_text"] or "",
                    anchor_label=seg.get("anchor_label") or f"段 {item.segment_idx + 1}",
                ),
                timeout=SUMMARY_SEGMENT_TIMEOUT_SECONDS,
            )
            if self._was_cancelled(item):
                self._segments_repo.set_status(seg["id"], "pending")
                await self._emit_segment_event(
                    item.book_id,
                    {
                        "type": "segment_status",
                        "idx": item.segment_idx,
                        "status": "pending",
                    },
                )
                return
            provider = self.router.last_provider or "unknown"
            model = self.router.last_model or ""
            resource_id = self.router.last_resource_id or provider
            self._segments_repo.update_summary(
                seg["id"],
                summary_json=summary_to_json(summary),
                label=summary.label,
                anchor_label=summary.anchor,
                status="ready",
                summary_provider=resource_id,
                summary_model=model,
            )
            book = self._books_repo.get(item.book_id)
            if book:
                from lumina_core.search.fts import index_segment

                updated = self._segments_repo.get_by_index(item.book_id, item.segment_idx)
                if updated:
                    index_segment(self.conn, book, updated)
            await self._emit_segment_event(
                item.book_id,
                segment_ready_event_payload(
                    summary,
                    idx=item.segment_idx,
                    resource_id=resource_id,
                    model=model,
                ),
            )
            await self.enqueue_translate(item.book_id, seg["id"], item.segment_idx)
            self._books_repo.maybe_mark_summarized(item.book_id)
        except Exception:
            if self._was_cancelled(item):
                self._segments_repo.set_status(seg["id"], "pending")
                await self._emit_segment_event(
                    item.book_id,
                    {
                        "type": "segment_status",
                        "idx": item.segment_idx,
                        "status": "pending",
                    },
                )
                return
            retry = (seg.get("retry_count") or 0) + 1
            status = "failed" if retry >= SUMMARY_JOB_MAX_RETRIES else "error"
            self._segments_repo.set_status(seg["id"], status, retry_count=retry)
            await self._emit_segment_event(
                item.book_id,
                {
                    "type": "segment_status",
                    "idx": item.segment_idx,
                    "status": status,
                    "retry_count": retry,
                },
            )
            if retry < SUMMARY_JOB_MAX_RETRIES:
                await self.enqueue_summarize(
                    item.book_id, seg["id"], item.segment_idx, high=True
                )

    async def _run_translate(self, item: JobItem) -> None:
        if self._was_cancelled(item):
            return
        if not self._book_needs_translation(item.book_id):
            return
        seg = self._segments_repo.get_by_index(item.book_id, item.segment_idx)
        if not seg or not seg.get("raw_text"):
            return
        try:
            translation = await translate_segment(
                self.router,
                raw_text=seg["raw_text"],
                target_language=self.target_language,
            )
            if self._was_cancelled(item):
                return
            self.conn.execute(
                "UPDATE segments SET translation = ? WHERE id = ?",
                (translation, seg["id"]),
            )
            self.conn.commit()
            await self.emit(
                item.book_id,
                {
                    "type": "translation_ready",
                    "idx": item.segment_idx,
                    "translation": translation,
                },
            )
        except Exception:
            logger.exception("Translation failed for segment %s", item.segment_idx)
