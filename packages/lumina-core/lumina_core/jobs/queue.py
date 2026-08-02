"""Background job queue with priority and chat preemption."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine

import sqlite3

from lumina_core.config import (
    PromptsConfig,
    SUMMARY_JOB_MAX_RETRIES,
    SUMMARY_SEGMENT_TIMEOUT_SECONDS,
    load_prompts_config,
)
from lumina_core.db.connection import db_transaction
from lumina_core.db.repos import BookRepo, SegmentRepo
from lumina_core.models.router import ProfileModelRouter
from lumina_core.ops.task_registry import TaskRegistry
from lumina_core.summarize.segment import (
    segment_ready_event_payload,
    summarize_job_timeout_seconds,
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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_key(item: JobItem) -> str:
    return f"{item.book_id}:{item.segment_id}:{item.kind.value}"


class JobQueue:
    def __init__(
        self,
        conn: sqlite3.Connection,
        router: ProfileModelRouter,
        *,
        target_language: str = "zh-CN",
        task_registry: TaskRegistry | None = None,
        prompts: PromptsConfig | None = None,
    ) -> None:
        self.conn = conn
        self.router = router
        self.target_language = target_language
        self.prompts = prompts or load_prompts_config()
        self._task_registry = task_registry
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
        self._queued_keys: set[str] = set()
        self._paused_backlog: dict[str, JobItem] = {}
        self._active_summarize: dict[tuple[str, int], dict[str, Any]] = {}

    def summarize_active_for_book(self, book_id: str) -> dict[str, Any] | None:
        for (bid, idx), state in self._active_summarize.items():
            if bid == book_id:
                return {
                    "segment_idx": idx,
                    "started_at": state.get("started_at"),
                    "llm_attempt": state.get("llm_attempt", 1),
                    "max_llm_attempts": state.get("max_llm_attempts"),
                }
        return None

    def summarize_active_by_book(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for (book_id, idx), state in self._active_summarize.items():
            out[book_id] = {
                "segment_idx": idx,
                "started_at": state.get("started_at"),
                "llm_attempt": state.get("llm_attempt", 1),
                "max_llm_attempts": state.get("max_llm_attempts"),
            }
        return out

    def _key_is_summarize_for_book(self, key: str, book_id: str) -> bool:
        prefix = f"{book_id}:"
        suffix = f":{JobKind.SUMMARIZE.value}"
        return key.startswith(prefix) and key.endswith(suffix)

    def _summarize_queued_count_for_book(self, book_id: str) -> int:
        return sum(
            1
            for key in self._queued_keys
            if self._key_is_summarize_for_book(key, book_id)
        )

    def _has_queued_summarize_jobs(self, book_id: str) -> bool:
        return self._summarize_queued_count_for_book(book_id) > 0

    def summarize_state_for_book(
        self, book_id: str, *, ready: int, total: int
    ) -> str:
        if total <= 0 or ready >= total:
            return "summarized"
        if self.summarize_active_for_book(book_id) is not None:
            return "running"
        if self.is_user_paused(book_id):
            return "paused"
        if self._has_queued_summarize_jobs(book_id):
            return "queued"
        return "idle"

    def summarize_state_by_book(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for book in self._books_repo.list_books():
            book_id = book["id"]
            progress = self._books_repo.summary_progress(book_id)
            ready = int(progress["summary_ready_count"])
            total = int(progress["summary_total_count"])
            out[book_id] = {
                "summarize_state": self.summarize_state_for_book(
                    book_id, ready=ready, total=total
                ),
                "summarize_queued_count": self._summarize_queued_count_for_book(
                    book_id
                ),
            }
        return out

    def summarize_overview(self) -> dict[str, Any]:
        counts = {
            "running": 0,
            "queued": 0,
            "paused": 0,
            "idle": 0,
            "summarized": 0,
        }
        for book in self._books_repo.list_books():
            if book.get("status") == "processing":
                continue
            book_id = book["id"]
            progress = self._books_repo.summary_progress(book_id)
            ready = int(progress["summary_ready_count"])
            total = int(progress["summary_total_count"])
            state = self.summarize_state_for_book(book_id, ready=ready, total=total)
            if state in counts:
                counts[state] += 1
        return {
            "counts": counts,
            "user_paused_all": self._user_paused_all,
        }

    def _set_active_summarize(
        self,
        book_id: str,
        segment_idx: int,
        *,
        started_at: str,
        max_llm_attempts: int | None = None,
        llm_attempt: int = 1,
    ) -> None:
        self._active_summarize[(book_id, segment_idx)] = {
            "started_at": started_at,
            "llm_attempt": llm_attempt,
            "max_llm_attempts": max_llm_attempts,
        }

    def _update_active_summarize(
        self,
        book_id: str,
        segment_idx: int,
        *,
        llm_attempt: int | None = None,
        max_llm_attempts: int | None = None,
    ) -> None:
        key = (book_id, segment_idx)
        state = self._active_summarize.get(key)
        if not state:
            return
        if llm_attempt is not None:
            state["llm_attempt"] = llm_attempt
        if max_llm_attempts is not None:
            state["max_llm_attempts"] = max_llm_attempts

    def _clear_active_summarize(self, book_id: str, segment_idx: int) -> None:
        self._active_summarize.pop((book_id, segment_idx), None)

    def _clear_active_summarize_for_book(self, book_id: str) -> None:
        for key in list(self._active_summarize.keys()):
            if key[0] == book_id:
                self._active_summarize.pop(key, None)

    def _clear_all_active_summarize(self) -> None:
        self._active_summarize.clear()

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
        from lumina_core.config import effective_concurrency

        resources = self.router.models.resources_for_profile("summarize")
        if not resources:
            return 1
        return max(1, effective_concurrency(resources[0]))

    def pause_ollama(self) -> None:
        from lumina_core.debug_agent_log import agent_log

        agent_log(
            hypothesis_id="A",
            location="queue.py:pause_ollama",
            message="ollama paused for chat preempt",
            data={"chat_preempted": True},
        )
        self._paused.clear()

    def resume_ollama(self) -> None:
        from lumina_core.debug_agent_log import agent_log

        agent_log(
            hypothesis_id="A",
            location="queue.py:resume_ollama",
            message="ollama resumed after chat",
            data={"chat_preempted": False},
        )
        self._paused.set()

    def diagnostics(self) -> dict[str, Any]:
        active_jobs = [
            {
                "book_id": item.book_id,
                "segment_idx": item.segment_idx,
                "kind": item.kind.value,
                "job_key": _job_key(item),
            }
            for item in self._active.values()
        ]
        paused_backlog_jobs = [
            {
                "book_id": item.book_id,
                "segment_idx": item.segment_idx,
                "kind": item.kind.value,
                "job_key": key,
            }
            for key, item in self._paused_backlog.items()
        ]
        return {
            "queue_depth": self._queue.qsize(),
            "active_jobs": active_jobs,
            "paused_backlog_depth": len(self._paused_backlog),
            "paused_backlog_jobs": paused_backlog_jobs,
            "worker_count": self._worker_count,
            "worker_target": self._worker_target(),
            "chat_preempted": not self._paused.is_set(),
            "user_paused_all": self._user_paused_all,
            "user_paused_books": sorted(self._user_paused_books),
        }

    def _register_job_task(self, item: JobItem) -> None:
        if not self._task_registry:
            return
        book = self._books_repo.get(item.book_id)
        title = (book or {}).get("title") or item.book_id
        kind_label = "摘要" if item.kind == JobKind.SUMMARIZE else "翻译"
        profile = "summarize" if item.kind == JobKind.SUMMARIZE else "translate"
        self._task_registry.register(
            kind=item.kind.value,  # type: ignore[arg-type]
            subject_type="book",
            subject_id=item.book_id,
            subject_label=title,
            detail=f"段 {item.segment_idx + 1} {kind_label}",
            profile=profile,
            job_key=_job_key(item),
        )

    def is_user_paused(self, book_id: str) -> bool:
        if book_id in self._user_paused_books:
            return True
        return self._user_paused_all

    def unpause_book(self, book_id: str) -> None:
        """Clear per-book pause; if global pause is on, clear it so this book can run."""
        self._user_paused_books.discard(book_id)
        if self._user_paused_all:
            self._user_paused_all = False

    def _is_job_scheduled(self, job_key: str) -> bool:
        return (
            job_key in self._active
            or job_key in self._paused_backlog
            or job_key in self._queued_keys
        )

    def _suspend_single(self, item: JobItem) -> None:
        key = _job_key(item)
        self._paused_backlog[key] = item
        if self._task_registry:
            self._task_registry.pause_by_job_key(key)

    async def enqueue_summarize(
        self, book_id: str, segment_id: str, segment_idx: int, *, high: bool = False
    ) -> None:
        if self.is_user_paused(book_id):
            return
        priority = 0 if high else segment_idx + 1
        job = JobItem(
            priority=priority,
            book_id=book_id,
            segment_id=segment_id,
            segment_idx=segment_idx,
            kind=JobKind.SUMMARIZE,
        )
        key = _job_key(job)
        if self._is_job_scheduled(key):
            return
        await self._queue.put(job)
        self._queued_keys.add(key)
        self._register_job_task(job)
        self.ensure_workers()

    def _book_needs_translation(self, book_id: str) -> bool:
        book = self._books_repo.get(book_id)
        if not book:
            return False
        text_sample: str | None = None
        if not book.get("language"):
            first = self._segments_repo.get_by_index(book_id, 0)
            if first:
                text_sample = (first.get("raw_text") or "")[:2000]
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
        job = JobItem(
            priority=1000 + segment_idx,
            book_id=book_id,
            segment_id=segment_id,
            segment_idx=segment_idx,
            kind=JobKind.TRANSLATE,
        )
        key = _job_key(job)
        if self._is_job_scheduled(key):
            return
        await self._queue.put(job)
        self._queued_keys.add(key)
        self._register_job_task(job)
        self.ensure_workers()

    async def enqueue_book_prefetch(self, book_id: str) -> None:
        if self.is_user_paused(book_id):
            return
        await self._recover_stale_running(book_id)
        segments = self._segments_repo.list_for_book(book_id, include_body=False)
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
        segments = self._segments_repo.list_for_book(book_id, include_body=False)
        for seg in segments:
            self._segments_repo.set_status(seg["id"], "pending", retry_count=0)
            await self.enqueue_summarize(
                book_id, seg["id"], seg["idx"], high=True
            )
        return len(segments)

    async def stop_book(self, book_id: str) -> None:
        self._user_paused_books.add(book_id)
        await self._suspend_jobs(lambda item: item.book_id == book_id)
        self._clear_active_summarize_for_book(book_id)
        await self._reset_running_segments(book_id)
        await self.emit(
            book_id,
            {"type": "summarize_paused", "scope": "book", "book_id": book_id},
        )

    async def stop_all(self) -> None:
        self._user_paused_all = True
        self._user_paused_books.clear()
        await self._suspend_jobs(lambda _item: True)
        self._clear_all_active_summarize()
        books = self._books_repo.list_books()
        for book in books:
            await self._reset_running_segments(book["id"])
            await self.emit(
                book["id"],
                {"type": "summarize_paused", "scope": "all", "book_id": book["id"]},
            )

    async def start_book(self, book_id: str) -> None:
        self.unpause_book(book_id)
        await self._restore_suspended(book_id)
        await self._reset_segments_for_user_resume(book_id)
        await self.enqueue_book_prefetch(book_id)
        await self.emit(
            book_id,
            {"type": "summarize_resumed", "scope": "book", "book_id": book_id},
        )

    async def start_all(self) -> None:
        self._user_paused_all = False
        self._user_paused_books.clear()
        await self._restore_suspended(None)
        books = self._books_repo.list_books()
        for book in books:
            await self._reset_segments_for_user_resume(book["id"])
            await self.enqueue_book_prefetch(book["id"])
            await self.emit(
                book["id"],
                {"type": "summarize_resumed", "scope": "all", "book_id": book["id"]},
            )

    async def _suspend_jobs(self, match: Callable[[JobItem], bool]) -> None:
        kept: list[JobItem] = []
        while True:
            try:
                item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            self._queue.task_done()
            key = _job_key(item)
            self._queued_keys.discard(key)
            if match(item):
                self._paused_backlog[key] = item
                if self._task_registry:
                    self._task_registry.pause_by_job_key(key)
            else:
                kept.append(item)
        for item in kept:
            key = _job_key(item)
            await self._queue.put(item)
            self._queued_keys.add(key)

        for key, item in list(self._active.items()):
            if match(item):
                self._paused_backlog[key] = item
                self._cancelled.add(key)
                if self._task_registry:
                    self._task_registry.pause_by_job_key(key)

    async def _restore_suspended(self, book_id: str | None) -> None:
        """Move paused backlog jobs back to the main queue (book_id=None restores all)."""
        to_restore: list[tuple[str, JobItem]] = []
        for key, item in self._paused_backlog.items():
            if book_id is None or item.book_id == book_id:
                to_restore.append((key, item))
        for key, item in to_restore:
            del self._paused_backlog[key]
            self._cancelled.discard(key)
            await self._queue.put(item)
            self._queued_keys.add(key)
            if self._task_registry:
                self._task_registry.requeue_by_job_key(key)
        if to_restore:
            self.ensure_workers()

    async def _reset_running_segments(self, book_id: str) -> None:
        for seg in self._segments_repo.list_for_book(book_id, include_body=False):
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
        for seg in self._segments_repo.list_for_book(book_id, include_body=False):
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
        for seg in self._segments_repo.list_for_book(book_id, include_body=False):
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
            self._queued_keys.discard(key)
            try:
                if self.is_user_paused(item.book_id):
                    self._suspend_single(item)
                    continue
                self._active[key] = item
                if self._task_registry:
                    self._task_registry.mark_running_by_job_key(key)
                try:
                    if item.kind == JobKind.SUMMARIZE:
                        await self._run_summarize(item)
                    elif item.kind == JobKind.TRANSLATE:
                        await self._run_translate(item)
                finally:
                    if self._task_registry:
                        if self._was_cancelled(item):
                            record = self._task_registry.get_by_job_key(key)
                            if record and record.status == "paused":
                                pass
                            elif self.is_user_paused(item.book_id):
                                self._task_registry.pause_by_job_key(key)
                            else:
                                self._task_registry.cancel_by_job_key(key)
                        else:
                            record = self._task_registry.get_by_job_key(key)
                            if record:
                                self._task_registry.update_resource(
                                    record.id, self.router.last_resource_id
                                )
                            self._task_registry.complete_by_job_key(key)
                    self._active.pop(key, None)
                    self._cancelled.discard(key)
            except Exception:
                logger.exception("Job failed: %s", item)
                if self._task_registry:
                    self._task_registry.fail_by_job_key(key, "worker exception")
            finally:
                self._queue.task_done()

    async def _run_summarize(self, item: JobItem) -> None:
        import time

        from lumina_core.debug_agent_log import agent_log

        seg = self._segments_repo.get_by_index(item.book_id, item.segment_idx)
        if not seg:
            return
        if self._was_cancelled(item):
            return
        job_started = time.time()
        job_key = _job_key(item)
        text_len = len(seg.get("raw_text") or "")
        agent_log(
            hypothesis_id="E",
            location="queue.py:_run_summarize:start",
            message="summarize job started",
            data={
                "book_id": item.book_id,
                "segment_idx": item.segment_idx,
                "retry_count": seg.get("retry_count") or 0,
                "text_len": text_len,
                "queue_depth": self._queue.qsize(),
                "active_jobs": len(self._active),
                "chat_preempted": not self._paused.is_set(),
            },
        )
        started_at = _utc_now()
        running_marked = False

        async def _mark_running() -> None:
            nonlocal running_marked
            if running_marked:
                return
            running_marked = True
            self._set_active_summarize(
                item.book_id,
                item.segment_idx,
                started_at=started_at,
            )
            self._segments_repo.set_status(seg["id"], "running")
            await self._emit_segment_event(
                item.book_id,
                {
                    "type": "segment_status",
                    "idx": item.segment_idx,
                    "status": "running",
                    "started_at": started_at,
                },
            )

        job_timeout = summarize_job_timeout_seconds(self.router, self.prompts)
        try:
            async def _on_progress(payload: dict[str, Any]) -> None:
                payload.setdefault("idx", item.segment_idx)
                if payload.get("phase") == "llm_start":
                    await _mark_running()
                llm_attempt = payload.get("llm_attempt")
                max_llm_attempts = payload.get("max_llm_attempts")
                if llm_attempt is not None or max_llm_attempts is not None:
                    self._update_active_summarize(
                        item.book_id,
                        item.segment_idx,
                        llm_attempt=llm_attempt,
                        max_llm_attempts=max_llm_attempts,
                    )
                if self._task_registry:
                    self._task_registry.update_progress_by_job_key(
                        job_key,
                        llm_attempt=llm_attempt,
                        max_llm_attempts=max_llm_attempts,
                        duration_s=round(time.time() - job_started, 2),
                    )
                await self._emit_segment_event(item.book_id, payload)

            result = await asyncio.wait_for(
                summarize_segment(
                    self.router,
                    raw_text=seg["raw_text"] or "",
                    anchor_label=seg.get("anchor_label") or f"段 {item.segment_idx + 1}",
                    on_progress=_on_progress,
                    prompts=self.prompts,
                ),
                timeout=job_timeout,
            )
            if self._was_cancelled(item):
                self._clear_active_summarize(item.book_id, item.segment_idx)
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
            summary_duration_s = round(time.time() - job_started, 2)
            provider = self.router.last_provider or "unknown"
            model = self.router.last_model or ""
            resource_id = self.router.last_resource_id or provider
            self._segments_repo.update_summary(
                seg["id"],
                summary_json=summary_to_json(result.summary),
                label=result.summary.label,
                anchor_label=result.summary.anchor,
                status="ready",
                summary_provider=resource_id,
                summary_model=model,
                summary_duration_s=summary_duration_s,
                summary_llm_attempts=result.llm_attempts,
            )
            book = self._books_repo.get(item.book_id)
            if book:
                from lumina_core.search.fts import index_segment

                updated = self._segments_repo.get_by_index(item.book_id, item.segment_idx)
                if updated:
                    index_segment(self.conn, book, updated)
            self._clear_active_summarize(item.book_id, item.segment_idx)
            await self._emit_segment_event(
                item.book_id,
                segment_ready_event_payload(
                    result.summary,
                    idx=item.segment_idx,
                    resource_id=resource_id,
                    model=model,
                    summary_duration_s=summary_duration_s,
                    summary_llm_attempts=result.llm_attempts,
                ),
            )
            if self._task_registry:
                self._task_registry.update_progress_by_job_key(
                    job_key,
                    llm_attempt=result.llm_attempts,
                    duration_s=summary_duration_s,
                )
            await self.enqueue_translate(item.book_id, seg["id"], item.segment_idx)
            self._books_repo.maybe_mark_summarized(item.book_id)
            agent_log(
                hypothesis_id="E",
                location="queue.py:_run_summarize:success",
                message="summarize job succeeded",
                data={
                    "book_id": item.book_id,
                    "segment_idx": item.segment_idx,
                    "duration_s": summary_duration_s,
                    "llm_attempts": result.llm_attempts,
                    "resource_id": resource_id,
                    "provider": provider,
                    "model": model,
                },
            )
        except Exception as exc:
            summary_duration_s = round(time.time() - job_started, 2)
            agent_log(
                hypothesis_id="E",
                location="queue.py:_run_summarize:error",
                message="summarize job failed",
                data={
                    "book_id": item.book_id,
                    "segment_idx": item.segment_idx,
                    "duration_s": summary_duration_s,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:500],
                },
            )
            self._clear_active_summarize(item.book_id, item.segment_idx)
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
            if isinstance(exc, TimeoutError):
                llm_retries = max(1, job_timeout // SUMMARY_SEGMENT_TIMEOUT_SECONDS)
                err_msg = (
                    f"摘要超时（已等待 {summary_duration_s:.0f}s，"
                    f"单段上限 {job_timeout}s，含最多 {llm_retries} 次生成）"
                )
            else:
                err_msg = str(exc)[:300] or type(exc).__name__
            self._segments_repo.set_status(seg["id"], status, retry_count=retry)
            await self._emit_segment_event(
                item.book_id,
                {
                    "type": "segment_status",
                    "idx": item.segment_idx,
                    "status": status,
                    "retry_count": retry,
                    "summary_duration_s": summary_duration_s,
                    "message": err_msg,
                },
            )
            if self._task_registry:
                self._task_registry.update_progress_by_job_key(
                    job_key,
                    duration_s=summary_duration_s,
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
                prompts=self.prompts,
            )
            if self._was_cancelled(item):
                return
            with db_transaction(self.conn):
                self.conn.execute(
                    "UPDATE segments SET translation = ? WHERE id = ?",
                    (translation, seg["id"]),
                )
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
