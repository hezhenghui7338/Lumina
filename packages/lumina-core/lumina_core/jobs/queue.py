"""Background job queue with priority and chat preemption."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine

import sqlite3

from lumina_core.config import MAX_SUMMARY_RETRIES, JobConcurrency
from lumina_core.db.repos import BookRepo, SegmentRepo
from lumina_core.models.router import ProfileModelRouter
from lumina_core.summarize.segment import summarize_segment, summary_to_json
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


class JobQueue:
    def __init__(
        self,
        conn: sqlite3.Connection,
        router: ProfileModelRouter,
        concurrency: JobConcurrency,
        *,
        target_language: str = "zh-CN",
    ) -> None:
        self.conn = conn
        self.router = router
        self.concurrency = concurrency
        self.target_language = target_language
        self._queue: asyncio.PriorityQueue[JobItem] = asyncio.PriorityQueue()
        self._paused = asyncio.Event()
        self._paused.set()
        self._workers_started = False
        self._event_callback: EventCallback | None = None
        self._books_repo = BookRepo(conn)
        self._segments_repo = SegmentRepo(conn)

    def set_event_callback(self, cb: EventCallback) -> None:
        self._event_callback = cb

    async def emit(self, book_id: str, payload: dict[str, Any]) -> None:
        if self._event_callback:
            await self._event_callback(book_id, payload)

    def ensure_workers(self) -> None:
        if self._workers_started:
            return
        self._workers_started = True
        for _ in range(max(1, self.concurrency.ollama)):
            asyncio.create_task(self._worker())

    def pause_ollama(self) -> None:
        self._paused.clear()

    def resume_ollama(self) -> None:
        self._paused.set()

    async def enqueue_summarize(
        self, book_id: str, segment_id: str, segment_idx: int, *, high: bool = False
    ) -> None:
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

    async def enqueue_translate(
        self, book_id: str, segment_id: str, segment_idx: int
    ) -> None:
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
        segments = self._segments_repo.list_for_book(book_id)
        for seg in segments:
            if seg["summary_status"] in ("pending", "failed"):
                await self.enqueue_summarize(
                    book_id, seg["id"], seg["idx"], high=(seg["idx"] == 0)
                )

    async def _worker(self) -> None:
        while True:
            await self._paused.wait()
            item = await self._queue.get()
            try:
                if item.kind == JobKind.SUMMARIZE:
                    await self._run_summarize(item)
                elif item.kind == JobKind.TRANSLATE:
                    await self._run_translate(item)
            except Exception:
                logger.exception("Job failed: %s", item)
            finally:
                self._queue.task_done()

    async def _run_summarize(self, item: JobItem) -> None:
        seg = self._segments_repo.get_by_index(item.book_id, item.segment_idx)
        if not seg:
            return
        self._segments_repo.set_status(seg["id"], "running")
        await self.emit(
            item.book_id,
            {"type": "segment_status", "idx": item.segment_idx, "status": "running"},
        )
        try:
            summary = await summarize_segment(
                self.router,
                raw_text=seg["raw_text"] or "",
                anchor_label=seg.get("anchor_label") or f"段 {item.segment_idx + 1}",
            )
            self._segments_repo.update_summary(
                seg["id"],
                summary_json=summary_to_json(summary),
                label=summary.label,
                anchor_label=summary.anchor,
                status="ready",
            )
            book = self._books_repo.get(item.book_id)
            if book:
                from lumina_core.search.fts import index_segment

                updated = self._segments_repo.get_by_index(item.book_id, item.segment_idx)
                if updated:
                    index_segment(self.conn, book, updated)
            await self.emit(
                item.book_id,
                {
                    "type": "segment_ready",
                    "idx": item.segment_idx,
                    "label": summary.label,
                },
            )
            await self.enqueue_translate(item.book_id, seg["id"], item.segment_idx)
        except Exception:
            retry = (seg.get("retry_count") or 0) + 1
            status = "failed" if retry >= MAX_SUMMARY_RETRIES else "error"
            self._segments_repo.set_status(seg["id"], status, retry_count=retry)
            await self.emit(
                item.book_id,
                {
                    "type": "segment_status",
                    "idx": item.segment_idx,
                    "status": status,
                    "retry_count": retry,
                },
            )
            if retry < MAX_SUMMARY_RETRIES:
                await self.enqueue_summarize(
                    item.book_id, seg["id"], item.segment_idx, high=True
                )

    async def _run_translate(self, item: JobItem) -> None:
        seg = self._segments_repo.get_by_index(item.book_id, item.segment_idx)
        if not seg or not seg.get("raw_text"):
            return
        try:
            translation = await translate_segment(
                self.router,
                raw_text=seg["raw_text"],
                target_language=self.target_language,
            )
            self.conn.execute(
                "UPDATE segments SET translation = ? WHERE id = ?",
                (translation, seg["id"]),
            )
            self.conn.commit()
            await self.emit(
                item.book_id,
                {"type": "translation_ready", "idx": item.segment_idx},
            )
        except Exception:
            logger.exception("Translation failed for segment %s", item.segment_idx)
