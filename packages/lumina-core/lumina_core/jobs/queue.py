"""Background job queue with priority and chat preemption."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine, TypeVar

import sqlite3

from lumina_core.config import (
    PromptsConfig,
    SUMMARY_JOB_MAX_RETRIES,
    SUMMARY_SEGMENT_TIMEOUT_SECONDS,
    load_prompts_config,
)
from lumina_core.db.connection import db_transaction
from lumina_core.db.repos import BookRepo, SegmentRepo, SummaryNodeRepo
from lumina_core.models.router import ProfileModelRouter
from lumina_core.ops.task_registry import TaskRegistry
from lumina_core.summarize.segment import (
    SUMMARY_CONTEXT_QUERY_LIMIT,
    build_summary_context,
    segment_ready_event_payload,
    summarize_job_timeout_seconds,
    summarize_segment,
    summary_to_json,
)
from lumina_core.translate.language import book_needs_translation, infer_language
from lumina_core.translate.translator import translate_segment

logger = logging.getLogger(__name__)

# Book index rollup is a slow serial LLM grind that only "chat with whole book"
# needs. It runs on its own single-slot channel so it can never take the workers
# (or the LLM slots) that segment summarization needs.
ROLLUP_WORKER_TARGET = 1


class JobKind(str, Enum):
    SUMMARIZE = "summarize"
    TRANSLATE = "translate"
    ROLLUP = "book_index"


@dataclass(order=True)
class JobItem:
    priority: int
    book_id: str = field(compare=False)
    segment_id: str = field(compare=False)
    segment_idx: int = field(compare=False)
    kind: JobKind = field(compare=False)
    retry_count: int = field(default=0, compare=False)
    summary_tier: str = field(default="normal", compare=False)


EventCallback = Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]
T = TypeVar("T")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_key(item: JobItem) -> str:
    suffix = (
        f"{item.kind.value}:{item.summary_tier}"
        if item.kind == JobKind.SUMMARIZE
        else item.kind.value
    )
    return f"{item.book_id}:{item.segment_id}:{suffix}"


class JobQueue:
    def __init__(
        self,
        conn: sqlite3.Connection,
        router: ProfileModelRouter,
        *,
        target_language: str = "zh-CN",
        auto_start_summary: bool = False,
        task_registry: TaskRegistry | None = None,
        prompts: PromptsConfig | None = None,
    ) -> None:
        self.conn = conn
        self.router = router
        self.target_language = target_language
        self.auto_start_summary = auto_start_summary
        self.prompts = prompts or load_prompts_config()
        self._task_registry = task_registry
        self._queue: asyncio.PriorityQueue[JobItem] = asyncio.PriorityQueue()
        # Rollup gets its own queue so a long book index can never starve summarize.
        self._rollup_queue: asyncio.PriorityQueue[JobItem] = asyncio.PriorityQueue()
        self._paused = asyncio.Event()
        self._paused.set()
        self._worker_count = 0
        self._workers: list[asyncio.Task[None]] = []
        self._rollup_workers: list[asyncio.Task[None]] = []
        self._event_callback: EventCallback | None = None
        self._books_repo = BookRepo(conn)
        self._segments_repo = SegmentRepo(conn)
        self._nodes_repo = SummaryNodeRepo(conn)
        # User-controlled summarize pause (separate from chat pause_ollama)
        self._user_paused_all = False
        self._user_paused_books: set[str] = set()
        self._active: dict[str, JobItem] = {}
        self._cancelled: set[str] = set()
        self._queued_keys: set[str] = set()
        # O(1) summarize queued counts for GET /books (avoids O(N×Q) key scans).
        self._summarize_queued_by_book: dict[str, int] = {}
        self._paused_backlog: dict[str, JobItem] = {}
        self._active_summarize: dict[tuple[str, int], dict[str, Any]] = {}
        self._book_summarize_locks: dict[str, asyncio.Lock] = {}
        self._desired_summary_tier: dict[str, str] = {}
        # idle | active | paused — persisted so sidecar restart cannot dump the queue.
        self._intent_cache: dict[str, str] = {}
        self._shutting_down = False
        self._resume_lock = asyncio.Lock()
        # Fast recover path holds this so GET /books skips resume_orphaned_active.
        self._startup_recovering = False
        # Cold-start gate phases for GET /startup/status (not /health).
        self._startup_data_phase = "pending"  # pending|running|done
        self._startup_cache_phase = "pending"  # pending|running|done
        # Drop trees + catalog backfill + summarize resume (must not block open/read).
        self._startup_deferred_task: asyncio.Task[None] | None = None
        # Backward-compatible alias used by older tests / call sites.
        self._catalog_backfill_task: asyncio.Task[None] | None = None

    def startup_data_phase(self) -> str:
        return self._startup_data_phase

    def startup_cache_phase(self) -> str:
        return self._startup_cache_phase

    def summarize_active_for_book(self, book_id: str) -> dict[str, Any] | None:
        for (bid, idx), state in self._active_summarize.items():
            if bid == book_id:
                return {
                    "segment_idx": idx,
                    "started_at": state.get("started_at"),
                    "llm_attempt": state.get("llm_attempt", 1),
                    "max_llm_attempts": state.get("max_llm_attempts"),
                    "summary_tier": state.get("summary_tier", "normal"),
                }
        return None

    def summary_tier_for_book(self, book_id: str) -> str:
        if book_id not in self._desired_summary_tier:
            self._desired_summary_tier[book_id] = (
                self._segments_repo.summary_tier_for_book(book_id)
            )
        return self._desired_summary_tier[book_id]

    def summarize_active_by_book(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for (book_id, idx), state in self._active_summarize.items():
            out[book_id] = {
                "segment_idx": idx,
                "started_at": state.get("started_at"),
                "llm_attempt": state.get("llm_attempt", 1),
                "max_llm_attempts": state.get("max_llm_attempts"),
                "summary_tier": state.get("summary_tier", "normal"),
            }
        return out

    def _is_summarize_queued_key(self, key: str) -> bool:
        return f":{JobKind.SUMMARIZE.value}:" in key

    def _book_id_from_job_key(self, key: str) -> str:
        return key.split(":", 1)[0]

    def _add_queued_key(self, key: str) -> bool:
        if key in self._queued_keys:
            return False
        self._queued_keys.add(key)
        if self._is_summarize_queued_key(key):
            book_id = self._book_id_from_job_key(key)
            self._summarize_queued_by_book[book_id] = (
                self._summarize_queued_by_book.get(book_id, 0) + 1
            )
        return True

    def _discard_queued_key(self, key: str) -> bool:
        if key not in self._queued_keys:
            return False
        self._queued_keys.discard(key)
        if self._is_summarize_queued_key(key):
            book_id = self._book_id_from_job_key(key)
            next_count = self._summarize_queued_by_book.get(book_id, 0) - 1
            if next_count <= 0:
                self._summarize_queued_by_book.pop(book_id, None)
            else:
                self._summarize_queued_by_book[book_id] = next_count
        return True

    def _clear_queued_keys(self) -> None:
        self._queued_keys.clear()
        self._summarize_queued_by_book.clear()

    def _summarize_queued_count_for_book(self, book_id: str) -> int:
        return int(self._summarize_queued_by_book.get(book_id, 0))

    def _has_queued_summarize_jobs(self, book_id: str) -> bool:
        return self._summarize_queued_count_for_book(book_id) > 0

    def _has_active_summarize_job(self, book_id: str) -> bool:
        return any(
            item.book_id == book_id and item.kind == JobKind.SUMMARIZE
            for item in self._active.values()
        )

    def _active_rollup_count(self) -> int:
        return sum(
            1 for item in self._active.values() if item.kind == JobKind.ROLLUP
        )

    def _has_scheduled_summarize_job(self, book_id: str) -> bool:
        return self._has_active_summarize_job(book_id) or self._has_queued_summarize_jobs(book_id)

    def has_book_work(self, book_id: str) -> bool:
        # Resegment-only path: still scans _queued_keys. List/polling uses
        # _summarize_queued_by_book (O(1)), not this helper.
        prefix = f"{book_id}:"
        return any(item.book_id == book_id for item in self._active.values()) or any(
            key.startswith(prefix) for key in self._queued_keys
        )

    def _intent_for(self, book_id: str) -> str:
        cached = self._intent_cache.get(book_id)
        if cached is not None:
            return cached
        book = self._books_repo.get(book_id)
        intent = (book or {}).get("summarize_intent") or "idle"
        self._intent_cache[book_id] = intent
        return intent

    def _set_intent(self, book_id: str, intent: str) -> None:
        if self._intent_cache.get(book_id) == intent:
            return
        self._intent_cache[book_id] = intent
        self._books_repo.update(book_id, summarize_intent=intent)

    async def _set_intent_async(self, book_id: str, intent: str) -> None:
        """Persist summarize intent without waiting for SQLite on the event loop."""
        if self._intent_cache.get(book_id) == intent:
            return
        self._intent_cache[book_id] = intent
        await self._run_db(
            lambda: self._books_repo.update(book_id, summarize_intent=intent)
        )

    def summarize_state_for_book(
        self, book_id: str, *, ready: int, total: int
    ) -> str:
        if total <= 0:
            # No segments yet: still 分段中, never 已摘要. Empty unread rows
            # are repaired to 导入失败; live imports stay processing.
            return "segmenting"
        if ready >= total:
            return "summarized"
        if self.is_user_paused(book_id) or self._intent_for(book_id) == "paused":
            return "paused"
        if (
            self.summarize_active_for_book(book_id) is not None
            or self._has_active_summarize_job(book_id)
        ):
            return "running"
        if (
            self._has_queued_summarize_jobs(book_id)
            or self._intent_for(book_id) == "active"
        ):
            return "queued"
        return "idle"

    def summarize_state_by_book(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for book in self._books_repo.list_books():
            book_id = book["id"]
            self._intent_cache[book_id] = book.get("summarize_intent") or "idle"
            ready = book.get("summary_ready_count")
            total = book.get("summary_total_count")
            segment_count = int(book.get("segment_count") or 0)
            if (
                ready is None
                or total is None
                or int(total) != segment_count
            ):
                progress = self._books_repo.refresh_summary_progress(book_id)
                ready = int(progress["summary_ready_count"])
                total = int(progress["summary_total_count"])
            else:
                ready = int(ready or 0)
                total = int(total or 0)
            out[book_id] = {
                "summarize_state": self.summarize_state_for_book(
                    book_id, ready=ready, total=total
                ),
                "summarize_queued_count": self._summarize_queued_count_for_book(
                    book_id
                ),
                "summary_tier": self._desired_summary_tier.get(book_id, "normal"),
            }
        return out

    def summarize_overview(self) -> dict[str, Any]:
        counts = {
            "running": 0,
            "queued": 0,
            "paused": 0,
            "idle": 0,
            "summarized": 0,
            "segmenting": 0,
        }
        for book in self._books_repo.list_books():
            if book.get("status") == "processing":
                counts["segmenting"] += 1
                continue
            if book.get("status") == "error":
                continue
            book_id = book["id"]
            ready = book.get("summary_ready_count")
            total = book.get("summary_total_count")
            segment_count = int(book.get("segment_count") or 0)
            if (
                ready is None
                or total is None
                or int(total) != segment_count
            ):
                progress = self._books_repo.refresh_summary_progress(book_id)
                ready = progress["summary_ready_count"]
                total = progress["summary_total_count"]
            else:
                ready = int(ready or 0)
                total = int(total or 0)
            state = self.summarize_state_for_book(book_id, ready=ready, total=total)
            if state in counts:
                counts[state] += 1
        indexing = self._active_rollup_count()
        counts["indexing"] = indexing
        return {
            "counts": counts,
            "indexing_queued": self._rollup_queue.qsize(),
            "stalled_reason": self._stalled_reason(
                running=counts["running"], queued=counts["queued"], indexing=indexing
            ),
            "user_paused_all": self._user_paused_all,
        }

    def _stalled_reason(
        self, *, running: int, queued: int, indexing: int
    ) -> str | None:
        """Explain why summarize work is queued while nothing is in progress.

        The UI must never render a bare 「0 进行中 · n 排队」 — that reads as a
        hang even when the machine is busy on something else.
        """
        if queued <= 0 or running > 0:
            return None
        if not self._paused.is_set():
            return "chat_preempt"
        if indexing > 0:
            return "indexing"
        if not [task for task in self._workers if not task.done()]:
            return "no_worker"
        if self._llm_slots_busy():
            return "llm_slots_busy"
        return "starting"

    def _llm_slots_busy(self) -> bool:
        """True when every LLM slot for the summarize profile is taken."""
        try:
            resources = self.router.models.resources_for_profile("summarize")
            runtime = {
                str(row.get("resource_id")): row
                for row in self.router.resource_runtime()
            }
        except Exception:  # pragma: no cover - mock routers may not expose a gate
            return False
        if not resources:
            return False
        for resource in resources:
            row = runtime.get(resource.id)
            if row is None:
                continue
            if int(row.get("available", 0)) > 0:
                return False
        return True

    def _set_active_summarize(
        self,
        book_id: str,
        segment_idx: int,
        *,
        started_at: str,
        max_llm_attempts: int | None = None,
        llm_attempt: int = 1,
        summary_tier: str = "normal",
    ) -> None:
        self._active_summarize[(book_id, segment_idx)] = {
            "started_at": started_at,
            "llm_attempt": llm_attempt,
            "max_llm_attempts": max_llm_attempts,
            "summary_tier": summary_tier,
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

    def _clear_active_summarize(
        self, book_id: str, segment_idx: int, *, summary_tier: str | None = None
    ) -> None:
        key = (book_id, segment_idx)
        state = self._active_summarize.get(key)
        if summary_tier is not None and state and state.get("summary_tier") != summary_tier:
            return
        self._active_summarize.pop(key, None)

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

    async def _run_db(self, fn: Callable[[], T]) -> T:
        """Keep SQLite/FTS off the uvicorn event loop (never-freeze)."""
        return await asyncio.to_thread(fn)

    def _summary_progress(self, book_id: str) -> dict[str, int]:
        return self._books_repo.summary_progress(book_id)

    async def _emit_segment_event(self, book_id: str, payload: dict[str, Any]) -> None:
        payload.update(await self._run_db(lambda: self._summary_progress(book_id)))
        await self.emit(book_id, payload)

    def refresh_workers(self) -> None:
        """Scale workers to match summarize profile concurrency."""
        self.ensure_workers()

    def ensure_workers(self) -> None:
        """Start enough workers to match summarize profile concurrency."""
        self._workers = [task for task in self._workers if not task.done()]
        self._worker_count = len(self._workers)
        target = self._worker_target()
        while self._worker_count < target:
            self._workers.append(
                asyncio.create_task(self._worker(self._queue))
            )
            self._worker_count += 1
        self._ensure_rollup_workers()

    def _ensure_rollup_workers(self) -> None:
        """Spawn the rollup worker only when there is actually index work."""
        self._rollup_workers = [
            task for task in self._rollup_workers if not task.done()
        ]
        if not self._has_pending_rollup_work():
            return
        while len(self._rollup_workers) < ROLLUP_WORKER_TARGET:
            self._rollup_workers.append(
                asyncio.create_task(self._worker(self._rollup_queue))
            )

    def _has_pending_rollup_work(self) -> bool:
        if self._rollup_queue.qsize() > 0:
            return True
        return any(
            item.kind == JobKind.ROLLUP for item in self._paused_backlog.values()
        )

    def _worker_target(self) -> int:
        from lumina_core.config import effective_concurrency

        resources = self.router.models.resources_for_profile("summarize")
        if not resources:
            return 1
        return max(1, effective_concurrency(resources[0]))

    def pause_ollama(self) -> None:
        self._paused.clear()

    def resume_ollama(self) -> None:
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
            "rollup_queue_depth": self._rollup_queue.qsize(),
            "active_jobs": active_jobs,
            "active_rollup_count": self._active_rollup_count(),
            "paused_backlog_depth": len(self._paused_backlog),
            "paused_backlog_jobs": paused_backlog_jobs,
            "worker_count": self._worker_count,
            "worker_target": self._worker_target(),
            "rollup_worker_count": len(
                [task for task in self._rollup_workers if not task.done()]
            ),
            "rollup_worker_target": ROLLUP_WORKER_TARGET,
            "chat_preempted": not self._paused.is_set(),
            "user_paused_all": self._user_paused_all,
            "user_paused_books": sorted(self._user_paused_books),
        }

    async def _register_job_task(self, item: JobItem) -> None:
        if not self._task_registry:
            return
        book = await self._run_db(lambda: self._books_repo.get(item.book_id))
        title = (book or {}).get("title") or item.book_id
        if item.kind == JobKind.ROLLUP:
            self._task_registry.register(
                kind="book_index",
                subject_type="book",
                subject_id=item.book_id,
                subject_label=title,
                detail="全书分层索引",
                profile="summarize",
                job_key=_job_key(item),
            )
            return
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
        """Clear pause for one book without releasing the rest of a global stop."""
        self._user_paused_books.discard(book_id)
        if self._intent_for(book_id) == "paused":
            # Caller may immediately set active (start_book). Otherwise the book
            # is merely unpaused, not queued — don't leave a sticky 已暂停 badge.
            self._set_intent(book_id, "idle")
        if self._user_paused_all:
            self._user_paused_all = False
            for book in self._books_repo.list_books():
                other_id = book["id"]
                if other_id == book_id:
                    continue
                self._user_paused_books.add(other_id)

    async def unpause_book_async(self, book_id: str) -> None:
        """Async queue path for unpausing without SQLite work on the event loop."""
        self._user_paused_books.discard(book_id)
        intent = self._intent_cache.get(book_id)
        if intent is None:
            book = await self._run_db(lambda: self._books_repo.get(book_id))
            intent = (book or {}).get("summarize_intent") or "idle"
            self._intent_cache[book_id] = intent
        if intent == "paused":
            await self._set_intent_async(book_id, "idle")
        if self._user_paused_all:
            self._user_paused_all = False
            books = await self._run_db(self._books_repo.list_books)
            for book in books:
                other_id = book["id"]
                if other_id != book_id:
                    self._user_paused_books.add(other_id)

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
        self,
        book_id: str,
        segment_id: str,
        segment_idx: int,
        *,
        high: bool = False,
        summary_tier: str | None = None,
    ) -> None:
        if self.is_user_paused(book_id):
            return
        if self._has_scheduled_summarize_job(book_id):
            return
        await self._set_intent_async(book_id, "active")
        # Prefer the earliest incomplete segment without scanning the whole book.
        earliest = await self._run_db(
            lambda: self._segments_repo.next_incomplete_segment(book_id)
        )
        if earliest is not None and int(earliest["idx"]) < segment_idx:
            segment_id = earliest["id"]
            segment_idx = int(earliest["idx"])
        priority = 0 if high else segment_idx + 1
        job = JobItem(
            priority=priority,
            book_id=book_id,
            segment_id=segment_id,
            segment_idx=segment_idx,
            kind=JobKind.SUMMARIZE,
            summary_tier=summary_tier
            or self._desired_summary_tier.get(book_id, "normal"),
        )
        key = _job_key(job)
        if key in self._active or key in self._queued_keys:
            return
        if key in self._paused_backlog:
            # A stale backlog entry on an un-paused book would silently block this
            # book from ever being summarized again; reclaim it instead.
            del self._paused_backlog[key]
            self._cancelled.discard(key)
        await self._register_job_task(job)
        await self._queue.put(job)
        self._add_queued_key(key)
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
        if not await self._run_db(lambda: self._book_needs_translation(book_id)):
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
        await self._register_job_task(job)
        await self._queue.put(job)
        self._add_queued_key(key)
        self.ensure_workers()

    async def clear_book_index(self, book_id: str) -> None:
        """Drop persisted tree and cancel in-flight rollup for this book."""
        await self._suspend_jobs(
            lambda item: item.book_id == book_id and item.kind == JobKind.ROLLUP
        )
        for key, item in list(self._paused_backlog.items()):
            if item.book_id != book_id or item.kind != JobKind.ROLLUP:
                continue
            del self._paused_backlog[key]
            self._cancelled.discard(key)
            if self._task_registry:
                self._task_registry.cancel_by_job_key(key)
        await self._run_db(
            lambda: (
                self._nodes_repo.delete_for_book(book_id),
                self._books_repo.update(book_id, index_status="idle"),
            )
        )

    async def enqueue_rollup(self, book_id: str) -> None:
        book = await self._run_db(lambda: self._books_repo.get(book_id))
        if not book:
            return
        progress = await self._run_db(lambda: self._books_repo.summary_progress(book_id))
        ready = int(progress["summary_ready_count"] or 0)
        total = int(progress["summary_total_count"] or 0)
        if total <= 0 or ready < total:
            return
        if book.get("index_status") == "ready" and await self._run_db(
            lambda: self._nodes_repo.get_root(book_id)
        ):
            return
        job = JobItem(
            priority=2000,
            book_id=book_id,
            segment_id="index",
            segment_idx=-1,
            kind=JobKind.ROLLUP,
        )
        key = _job_key(job)
        if self._is_job_scheduled(key):
            return
        await self._register_job_task(job)
        await self._rollup_queue.put(job)
        self._add_queued_key(key)
        self.ensure_workers()

    async def enqueue_book_prefetch(
        self, book_id: str, *, summary_tier: str | None = None
    ) -> None:
        if self.is_user_paused(book_id):
            return
        tier = summary_tier or self._desired_summary_tier.get(book_id, "normal")
        self._desired_summary_tier[book_id] = tier
        await self._set_intent_async(book_id, "active")
        await self._recover_stale_running(book_id)
        await self._enqueue_next_book_summary(book_id, summary_tier=tier)

    async def _enqueue_next_book_summary(
        self, book_id: str, *, summary_tier: str | None = None
    ) -> None:
        if self._shutting_down or self.is_user_paused(book_id):
            return
        if self._has_scheduled_summarize_job(book_id):
            return
        await self._recover_stale_running(book_id)
        tier = summary_tier or self._desired_summary_tier.get(book_id, "normal")
        seg = await self._run_db(
            lambda: self._segments_repo.next_incomplete_segment(book_id)
        )
        if seg is not None:
            await self.enqueue_summarize(
                book_id,
                seg["id"],
                seg["idx"],
                high=(seg["idx"] == 0),
                summary_tier=tier,
            )
            return
        await self._set_intent_async(book_id, "idle")

    async def recover_on_startup(self) -> None:
        """Fast path for time-to-read; defer cleanup and summarize resume.

        Product goal: after /health is green the user can open any ready book
        and paint text without waiting on document_tree cleanup, catalog
        backfill, or re-enqueueing every active summarize intent.

        Fast path (must stay short, then clear `_startup_recovering`):
          1. ensure_workers
          2. repair_stale_imports (orphan processing / 0-segment → 导入失败)

        Deferred (`_startup_deferred_task`):
          drop_stored_document_trees → catalog/label backfill → intent resume
          (maybe_mark_summarized / start_book / stale index+running repair).

        Startup deliberately does not enqueue any rollup. Ingest/resegment
        tasks do not survive a process restart, so any processing or 0-segment
        row here is an orphan.
        """
        from lumina_core.perf import record as perf_record

        t0 = time.perf_counter()
        perf_record(kind="op", name="recover_on_startup.begin", ms=0.0)
        self._startup_recovering = True
        self._startup_data_phase = "running"
        try:
            self.ensure_workers()
            await self._run_db(
                lambda: self._books_repo.repair_stale_imports(
                    restore_orphaned_resegment=True
                )
            )
        finally:
            self._startup_recovering = False
            self._startup_data_phase = "done"
            self.ensure_workers()
            perf_record(
                kind="op",
                name="recover_on_startup.fast_path",
                ms=(time.perf_counter() - t0) * 1000.0,
            )
        if self._shutting_down:
            return
        self._startup_cache_phase = "running"
        self._startup_deferred_task = asyncio.create_task(
            self._deferred_startup_work(),
            name="lumina-startup-deferred",
        )
        self._catalog_backfill_task = self._startup_deferred_task

    async def _deferred_startup_work(self) -> None:
        """Background startup work that must not starve open / segment reads."""
        try:
            await self._run_db(self._books_repo.drop_stored_document_trees)
            await asyncio.sleep(0)
            if self._shutting_down:
                return
            await self._run_db(self._segments_repo.backfill_catalog_cache)
            await asyncio.sleep(0)
            if self._shutting_down:
                return
            await self._run_db(self._segments_repo.backfill_prefix_labels)
            await asyncio.sleep(0)
            if self._shutting_down:
                return
            await self._resume_summarize_after_startup()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("deferred startup work failed")
        finally:
            if self._startup_cache_phase != "done":
                self._startup_cache_phase = "done"

    async def _resume_summarize_after_startup(self) -> None:
        """Rehydrate intent cache and re-enqueue active summarize books.

        Runs only from `_deferred_startup_work` so open/read is not blocked.
        """
        books = await self._run_db(self._books_repo.list_books)
        for book in books:
            if self._shutting_down:
                return
            book_id = book["id"]
            promoted = await self._run_db(
                lambda bid=book_id: self._books_repo.maybe_mark_summarized(bid)
            )
            if promoted:
                self._intent_cache[book_id] = "idle"
                await self._recover_stale_index(book)
                await asyncio.sleep(0)
                continue
            await self._recover_stale_running(book_id)
            await self._recover_stale_index(book)
            intent = book.get("summarize_intent") or "idle"
            self._intent_cache[book_id] = intent
            if intent == "paused":
                self._user_paused_books.add(book_id)
                await asyncio.sleep(0)
                continue
            if intent == "active" or self.auto_start_summary:
                tier = await self._run_db(
                    lambda bid=book_id: self._segments_repo.summary_tier_for_book(
                        bid
                    )
                )
                await self.start_book(
                    book_id,
                    summary_tier=tier,
                )
            await asyncio.sleep(0)
        self.ensure_workers()

    async def resume_orphaned_active(self) -> None:
        """Re-enqueue started books that have no in-memory job (lost worker/job)."""
        if (
            self._shutting_down
            or self._startup_recovering
            or self._resume_lock.locked()
        ):
            return
        async with self._resume_lock:
            books = await asyncio.to_thread(self._books_repo.list_books)
            for book in books:
                book_id = book["id"]
                intent = book.get("summarize_intent") or "idle"
                if intent != "active" or self.is_user_paused(book_id):
                    continue
                if self._has_scheduled_summarize_job(book_id):
                    continue
                await self._enqueue_next_book_summary(book_id)
            self.ensure_workers()

    async def _recover_stale_index(self, book: dict[str, Any]) -> None:
        """Reset a 'building' index with no active rollup (crash/restart orphan).

        Left alone, the ghost status makes every restart re-enqueue the rollup.
        """
        if book.get("index_status") != "building":
            return
        book_id = book["id"]
        if any(
            item.book_id == book_id and item.kind == JobKind.ROLLUP
            for item in self._active.values()
        ):
            return
        await self._run_db(
            lambda: self._books_repo.update(book_id, index_status="idle")
        )
        await self.emit(
            book_id,
            {"type": "book_index_progress", "index_status": "idle"},
        )

    async def enqueue_book_regenerate(
        self, book_id: str, *, summary_tier: str = "normal"
    ) -> int:
        """Force re-summarize every segment, including ready ones.

        This is the only book-level path that overwrites existing summaries.
        Clients must confirm with the user first — it is expensive.
        """
        await self._supersede_book_tier(book_id, summary_tier)
        await self.clear_book_index(book_id)
        await self.unpause_book_async(book_id)
        self._desired_summary_tier[book_id] = summary_tier
        await self._set_intent_async(book_id, "active")

        def _reset_all() -> list[dict[str, Any]]:
            segments = self._segments_repo.list_for_book(book_id, include_body=False)
            for seg in segments:
                self._segments_repo.reset_summary(
                    seg["id"], summary_tier=summary_tier
                )
            return segments

        segments = await self._run_db(_reset_all)
        await self._enqueue_next_book_summary(
            book_id, summary_tier=summary_tier
        )
        return len(segments)

    async def stop_book(self, book_id: str) -> None:
        self._user_paused_books.add(book_id)
        await self._set_intent_async(book_id, "paused")
        await self._suspend_jobs(lambda item: item.book_id == book_id)
        self._clear_active_summarize_for_book(book_id)
        await self._reset_running_segments(book_id)
        await self.emit(
            book_id,
            {"type": "summarize_paused", "scope": "book", "book_id": book_id},
        )

    async def prepare_book_resegment(self, book_id: str) -> bool:
        """Cancel stale segment jobs and wait until workers stop touching the book."""
        was_paused = self.is_user_paused(book_id)
        await self.stop_book(book_id)

        while any(item.book_id == book_id for item in self._active.values()):
            await asyncio.sleep(0.05)
        return was_paused

    def discard_book_suspended(self, book_id: str) -> None:
        """Discard jobs tied to segment IDs that are about to be replaced."""
        for key, item in list(self._paused_backlog.items()):
            if item.book_id != book_id:
                continue
            del self._paused_backlog[key]
            self._cancelled.discard(key)
            if self._task_registry:
                self._task_registry.cancel_by_job_key(key)

    def cancel_active_jobs_for_segments(
        self, book_id: str, segment_ids: set[str]
    ) -> None:
        """Abort in-flight jobs that already loaded stale segment text."""
        if not segment_ids:
            return
        for key, item in list(self._active.items()):
            if item.book_id != book_id or item.segment_id not in segment_ids:
                continue
            self._cancelled.add(key)
            if self._task_registry:
                self._task_registry.cancel_by_job_key(key)

    async def stop_all(self) -> None:
        self._user_paused_all = True
        self._user_paused_books.clear()
        await self._suspend_jobs(lambda _item: True)
        self._clear_all_active_summarize()
        books = await self._run_db(self._books_repo.list_books)
        for book in books:
            book_id = book["id"]
            progress = await self._run_db(
                lambda bid=book_id: self._books_repo.summary_progress(bid)
            )
            ready = int(progress["summary_ready_count"] or 0)
            total = int(progress["summary_total_count"] or 0)
            if total > 0 and ready < total:
                await self._set_intent_async(book_id, "paused")
            await self._reset_running_segments(book_id)
            await self.emit(
                book_id,
                {"type": "summarize_paused", "scope": "all", "book_id": book_id},
            )

    def _discard_queue(self, queue: asyncio.PriorityQueue[JobItem]) -> None:
        while True:
            try:
                item = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            queue.task_done()
            self._discard_queued_key(_job_key(item))

    async def shutdown(self) -> None:
        """Cancel in-flight workers without recording a user pause.

        Sidecar exit used to call stop_all(), which made the next boot treat
        every unfinished book as idle. Intent stays active so recover_on_startup
        can put them back in the queue.
        """
        self._shutting_down = True
        deferred = self._startup_deferred_task or self._catalog_backfill_task
        if deferred is not None and not deferred.done():
            deferred.cancel()
            try:
                await deferred
            except asyncio.CancelledError:
                pass
            self._startup_deferred_task = None
            self._catalog_backfill_task = None
        tasks = [
            task
            for task in (*self._workers, *self._rollup_workers)
            if not task.done()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._workers.clear()
        self._rollup_workers.clear()
        self._worker_count = 0
        self._clear_all_active_summarize()
        self._active.clear()
        self._clear_queued_keys()
        self._paused_backlog.clear()
        self._cancelled.clear()
        self._discard_queue(self._queue)
        self._discard_queue(self._rollup_queue)
        books = await self._run_db(self._books_repo.list_books)
        for book in books:
            await self._reset_running_segments(book["id"])

    async def _supersede_book_tier(self, book_id: str, summary_tier: str) -> None:
        """Cancel queued work from another tier without waiting on slow LLM calls."""
        previous = self._desired_summary_tier.get(book_id, "normal")
        self._desired_summary_tier[book_id] = summary_tier
        if previous == summary_tier:
            return
        await self._suspend_jobs(
            lambda item: item.book_id == book_id and item.kind == JobKind.SUMMARIZE
        )
        for key, item in list(self._paused_backlog.items()):
            if item.book_id != book_id or item.kind != JobKind.SUMMARIZE:
                continue
            del self._paused_backlog[key]
            if self._task_registry:
                self._task_registry.cancel_by_job_key(key)
        self._clear_active_summarize_for_book(book_id)

    async def start_book(
        self, book_id: str, *, summary_tier: str = "normal"
    ) -> None:
        """Resume summarization. A new tier applies only to incomplete segments.

        Ready summaries are kept even if the user switches to advanced/normal.
        Use enqueue_book_regenerate to overwrite the whole book.
        """
        await self._supersede_book_tier(book_id, summary_tier)
        await self.unpause_book_async(book_id)
        await self._set_intent_async(book_id, "active")
        await self._restore_suspended(book_id)
        await self._apply_tier_to_incomplete_segments(book_id, summary_tier)
        await self._reset_segments_for_user_resume(book_id)
        await self.enqueue_book_prefetch(book_id, summary_tier=summary_tier)
        await self.emit(
            book_id,
            {
                "type": "summarize_resumed",
                "scope": "book",
                "book_id": book_id,
                "summary_tier": summary_tier,
            },
        )

    async def start_all(self, *, summary_tier: str = "normal") -> None:
        self._user_paused_all = False
        self._user_paused_books.clear()
        books = await self._run_db(self._books_repo.list_books)
        for book in books:
            await self.start_book(book["id"], summary_tier=summary_tier)

    def _queue_for(self, item: JobItem) -> asyncio.PriorityQueue[JobItem]:
        return self._rollup_queue if item.kind == JobKind.ROLLUP else self._queue

    async def _drain_queue(
        self,
        queue: asyncio.PriorityQueue[JobItem],
        match: Callable[[JobItem], bool],
    ) -> None:
        kept: list[JobItem] = []
        while True:
            try:
                item = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            queue.task_done()
            key = _job_key(item)
            self._discard_queued_key(key)
            if match(item):
                self._paused_backlog[key] = item
                if self._task_registry:
                    self._task_registry.pause_by_job_key(key)
            else:
                kept.append(item)
        for item in kept:
            await queue.put(item)
            self._add_queued_key(_job_key(item))

    async def _suspend_jobs(self, match: Callable[[JobItem], bool]) -> None:
        await self._drain_queue(self._queue, match)
        await self._drain_queue(self._rollup_queue, match)

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
            await self._queue_for(item).put(item)
            self._add_queued_key(key)
            if self._task_registry:
                self._task_registry.requeue_by_job_key(key)
        if to_restore:
            self.ensure_workers()

    async def _reset_running_segments(self, book_id: str) -> None:
        segments = await self._run_db(
            lambda: self._segments_repo.reset_running_segments(book_id)
        )
        for seg in segments:
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
        segments = await self._run_db(
            lambda: self._segments_repo.reset_failed_segments(book_id)
        )
        for seg in segments:
            await self._emit_segment_event(
                book_id,
                {
                    "type": "segment_status",
                    "idx": seg["idx"],
                    "status": "pending",
                },
            )

    async def _apply_tier_to_incomplete_segments(
        self, book_id: str, summary_tier: str
    ) -> None:
        """Stamp a new tier onto pending/error/running segments; keep ready summaries."""
        await self._run_db(
            lambda: self._segments_repo.apply_summary_tier_to_incomplete(
                book_id, summary_tier
            )
        )

    async def _recover_stale_running(self, book_id: str) -> None:
        """Reset running segments with no active worker (crash/restart orphans)."""
        segments = await self._run_db(
            lambda: self._segments_repo.list_running_segments(book_id)
        )
        for seg in segments:
            if any(
                item.book_id == book_id
                and item.segment_id == seg["id"]
                and item.kind == JobKind.SUMMARIZE
                for item in self._active.values()
            ):
                continue
            await self._run_db(
                lambda sid=seg["id"]: self._segments_repo.set_status(sid, "pending")
            )
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

    def _is_superseded(self, item: JobItem) -> bool:
        return (
            item.kind == JobKind.SUMMARIZE
            and self._desired_summary_tier.get(item.book_id, "normal")
            != item.summary_tier
        )

    async def _worker(self, queue: asyncio.PriorityQueue[JobItem]) -> None:
        while True:
            await self._paused.wait()
            item = await queue.get()
            key = _job_key(item)
            try:
                if self._shutting_down:
                    self._discard_queued_key(key)
                    continue
                if self.is_user_paused(item.book_id):
                    self._discard_queued_key(key)
                    self._suspend_single(item)
                    continue
                self._active[key] = item
                self._discard_queued_key(key)
                if self._task_registry:
                    self._task_registry.mark_running_by_job_key(key)
                try:
                    if item.kind == JobKind.SUMMARIZE:
                        lock = self._book_summarize_locks.setdefault(
                            item.book_id, asyncio.Lock()
                        )
                        async with lock:
                            await self._run_summarize(item)
                    elif item.kind == JobKind.TRANSLATE:
                        await self._run_translate(item)
                    elif item.kind == JobKind.ROLLUP:
                        await self._run_rollup(item)
                finally:
                    was_cancelled = self._was_cancelled(item)
                    was_superseded = self._is_superseded(item)
                    if self._task_registry:
                        if was_cancelled:
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
                    if item.kind == JobKind.SUMMARIZE:
                        paused = was_cancelled and self.is_user_paused(
                            item.book_id
                        ) and not was_superseded
                        if not paused and not self._shutting_down:
                            try:
                                await self._enqueue_next_book_summary(item.book_id)
                            except Exception:
                                logger.exception(
                                    "Failed to enqueue next summary for %s",
                                    item.book_id,
                                )
            except Exception:
                logger.exception("Job failed: %s", item)
                self._active.pop(key, None)
                if self._task_registry:
                    self._task_registry.fail_by_job_key(key, "worker exception")
                if (
                    item.kind == JobKind.SUMMARIZE
                    and not self._shutting_down
                    and not self.is_user_paused(item.book_id)
                ):
                    try:
                        await self._enqueue_next_book_summary(item.book_id)
                    except Exception:
                        logger.exception(
                            "Failed to requeue summarize for %s", item.book_id
                        )
            finally:
                queue.task_done()

    def _load_summarize_inputs(
        self, book_id: str, segment_idx: int
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str]:
        seg = self._segments_repo.get_by_index(book_id, segment_idx)
        if not seg:
            return None, [], self.target_language
        rows = self._segments_repo.list_ready_summaries_before(
            book_id,
            segment_idx,
            limit=SUMMARY_CONTEXT_QUERY_LIMIT,
        )
        book = self._books_repo.get(book_id)
        target = (
            ((book or {}).get("target_language") or "").strip()
            or self.target_language
            or "zh-CN"
        )
        return seg, rows, target

    def _persist_ready_summary(
        self,
        *,
        book_id: str,
        segment_id: str,
        segment_idx: int,
        summary_json: str,
        label: str,
        anchor_label: str | None,
        resource_id: str,
        model: str,
        summary_tier: str,
        summary_duration_s: float,
        summary_llm_attempts: int,
    ) -> bool:
        self._segments_repo.update_summary(
            segment_id,
            summary_json=summary_json,
            label=label,
            anchor_label=anchor_label,
            status="ready",
            summary_provider=resource_id,
            summary_model=model,
            summary_tier=summary_tier,
            summary_duration_s=summary_duration_s,
            summary_llm_attempts=summary_llm_attempts,
        )
        book = self._books_repo.get(book_id)
        if book:
            from lumina_core.search.fts import index_segment

            updated = self._segments_repo.get_by_index(book_id, segment_idx)
            if updated:
                index_segment(self.conn, book, updated)
        done = bool(self._books_repo.maybe_mark_summarized(book_id))
        if done:
            self._intent_cache[book_id] = "idle"
        return done

    async def _run_summarize(self, item: JobItem) -> None:
        import time


        seg, context_rows, target_language = await self._run_db(
            lambda: self._load_summarize_inputs(item.book_id, item.segment_idx)
        )
        if not seg:
            return
        if self._was_cancelled(item):
            return
        background_context = build_summary_context(
            context_rows,
            current_chapter=seg.get("chapter"),
        )
        job_started = time.time()
        job_key = _job_key(item)
        text_len = len(seg.get("raw_text") or "")
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
                summary_tier=item.summary_tier,
            )
            await self._run_db(lambda: self._segments_repo.set_status(seg["id"], "running"))
            await self._emit_segment_event(
                item.book_id,
                {
                    "type": "segment_status",
                    "idx": item.segment_idx,
                    "status": "running",
                    "started_at": started_at,
                    "summary_tier": item.summary_tier,
                },
            )

        await _mark_running()
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
                    summary_tier=item.summary_tier,
                    on_progress=_on_progress,
                    prompts=self.prompts,
                    background_context=background_context,
                    target_language=target_language,
                ),
                timeout=job_timeout,
            )
            if self._was_cancelled(item):
                self._clear_active_summarize(
                    item.book_id,
                    item.segment_idx,
                    summary_tier=item.summary_tier,
                )
                if self._is_superseded(item):
                    return
                await self._run_db(
                    lambda: self._segments_repo.set_status(seg["id"], "pending")
                )
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
            await self._run_db(
                lambda: self._persist_ready_summary(
                    book_id=item.book_id,
                    segment_id=seg["id"],
                    segment_idx=item.segment_idx,
                    summary_json=summary_to_json(result.summary),
                    label=result.summary.label,
                    anchor_label=result.summary.anchor,
                    resource_id=resource_id,
                    model=model,
                    summary_tier=item.summary_tier,
                    summary_duration_s=summary_duration_s,
                    summary_llm_attempts=result.llm_attempts,
                )
            )
            self._clear_active_summarize(
                item.book_id,
                item.segment_idx,
                summary_tier=item.summary_tier,
            )
            await self._emit_segment_event(
                item.book_id,
                segment_ready_event_payload(
                    result.summary,
                    idx=item.segment_idx,
                    resource_id=resource_id,
                    model=model,
                    summary_tier=item.summary_tier,
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
        except Exception as exc:
            summary_duration_s = round(time.time() - job_started, 2)
            self._clear_active_summarize(
                item.book_id,
                item.segment_idx,
                summary_tier=item.summary_tier,
            )
            if self._was_cancelled(item):
                if self._is_superseded(item):
                    return
                await self._run_db(
                    lambda: self._segments_repo.set_status(seg["id"], "pending")
                )
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
            await self._run_db(
                lambda: self._segments_repo.set_status(
                    seg["id"], status, retry_count=retry
                )
            )
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

    async def _run_rollup(self, item: JobItem) -> None:
        from lumina_core.summarize.rollup import rollup_book

        if self._was_cancelled(item):
            return

        async def _on_progress(payload: dict[str, Any]) -> None:
            payload.setdefault("type", "book_index_progress")
            await self.emit(item.book_id, payload)

        status = await rollup_book(
            self.conn,
            self.router,
            item.book_id,
            prompts=self.prompts,
            cancelled=lambda: self._was_cancelled(item),
            on_progress=_on_progress,
            target_language=self.target_language,
        )
        event_type = "book_index_ready" if status == "ready" else "book_index_progress"
        await self.emit(
            item.book_id,
            {"type": event_type, "index_status": status},
        )

    async def _run_translate(self, item: JobItem) -> None:
        if self._was_cancelled(item):
            return
        if not await self._run_db(lambda: self._book_needs_translation(item.book_id)):
            return
        seg = await self._run_db(
            lambda: self._segments_repo.get_by_index(item.book_id, item.segment_idx)
        )
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

            def _save_translation() -> None:
                with db_transaction(self.conn):
                    self.conn.execute(
                        "UPDATE segments SET translation = ? WHERE id = ?",
                        (translation, seg["id"]),
                    )

            await self._run_db(_save_translation)
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
