"""In-memory registry for LLM task lifecycle (DEBUG / ops visibility)."""

from __future__ import annotations

import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

TaskKind = Literal[
    "summarize",
    "translate",
    "classify",
    "book_chat",
    "news_read",
    "news_chat",
]
TaskStatus = Literal["queued", "running", "paused", "completed", "failed", "cancelled"]
SubjectType = Literal["book", "article"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TaskRecord:
    id: str
    kind: TaskKind
    status: TaskStatus
    subject_type: SubjectType
    subject_id: str
    subject_label: str
    detail: str
    resource_id: str | None = None
    profile: str | None = None
    started_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    error: str | None = None
    cancellable: bool = False
    cancel_fn: Callable[[], None] | None = field(default=None, repr=False, compare=False)
    job_key: str | None = None
    llm_attempt: int | None = None
    max_llm_attempts: int | None = None
    duration_s: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "subject_label": self.subject_label,
            "detail": self.detail,
            "resource_id": self.resource_id,
            "profile": self.profile,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "error": self.error,
            "cancellable": self.cancellable,
            "job_key": self.job_key,
            "llm_attempt": self.llm_attempt,
            "max_llm_attempts": self.max_llm_attempts,
            "duration_s": self.duration_s,
        }


class TaskRegistry:
    """Track LLM tasks for ops/debug; completed tasks kept in a ring buffer."""

    def __init__(self, *, completed_limit: int = 50) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._by_job_key: dict[str, str] = {}
        self._completed: deque[str] = deque(maxlen=completed_limit)
        self._completed_limit = completed_limit

    def register(
        self,
        *,
        kind: TaskKind,
        subject_type: SubjectType,
        subject_id: str,
        subject_label: str,
        detail: str,
        profile: str | None = None,
        cancellable: bool = False,
        cancel_fn: Callable[[], None] | None = None,
        job_key: str | None = None,
        status: TaskStatus = "queued",
    ) -> TaskRecord:
        task_id = str(uuid.uuid4())
        now = _utc_now()
        record = TaskRecord(
            id=task_id,
            kind=kind,
            status=status,
            subject_type=subject_type,
            subject_id=subject_id,
            subject_label=subject_label,
            detail=detail,
            profile=profile,
            cancellable=cancellable,
            cancel_fn=cancel_fn,
            job_key=job_key,
            started_at=now,
            updated_at=now,
        )
        self._tasks[task_id] = record
        if job_key:
            self._by_job_key[job_key] = task_id
        return record

    def get(self, task_id: str) -> TaskRecord | None:
        return self._tasks.get(task_id)

    def get_by_job_key(self, job_key: str) -> TaskRecord | None:
        task_id = self._by_job_key.get(job_key)
        if not task_id:
            return None
        return self._tasks.get(task_id)

    def mark_running(
        self,
        task_id: str,
        *,
        resource_id: str | None = None,
    ) -> None:
        record = self._tasks.get(task_id)
        if not record:
            return
        record.status = "running"
        record.started_at = _utc_now()
        record.duration_s = None
        record.updated_at = _utc_now()
        if resource_id:
            record.resource_id = resource_id

    def mark_running_by_job_key(
        self,
        job_key: str,
        *,
        resource_id: str | None = None,
    ) -> None:
        task_id = self._by_job_key.get(job_key)
        if task_id:
            self.mark_running(task_id, resource_id=resource_id)

    def update_resource(self, task_id: str, resource_id: str | None) -> None:
        record = self._tasks.get(task_id)
        if not record:
            return
        record.resource_id = resource_id
        record.updated_at = _utc_now()

    def update_progress_by_job_key(
        self,
        job_key: str,
        *,
        llm_attempt: int | None = None,
        max_llm_attempts: int | None = None,
        duration_s: float | None = None,
    ) -> None:
        record = self.get_by_job_key(job_key)
        if not record:
            return
        if llm_attempt is not None:
            record.llm_attempt = llm_attempt
        if max_llm_attempts is not None:
            record.max_llm_attempts = max_llm_attempts
        if duration_s is not None:
            record.duration_s = round(duration_s, 2)
        record.updated_at = _utc_now()

    def complete(self, task_id: str, *, duration_s: float | None = None) -> None:
        record = self._tasks.get(task_id)
        if record and duration_s is not None:
            record.duration_s = round(duration_s, 2)
        self._finish(task_id, "completed")

    def complete_by_job_key(self, job_key: str, *, duration_s: float | None = None) -> None:
        task_id = self._by_job_key.get(job_key)
        if task_id:
            self.complete(task_id, duration_s=duration_s)

    def fail(self, task_id: str, error: str, *, duration_s: float | None = None) -> None:
        record = self._tasks.get(task_id)
        if not record:
            return
        record.status = "failed"
        record.error = error
        if duration_s is not None:
            record.duration_s = round(duration_s, 2)
        record.updated_at = _utc_now()
        self._archive(record)

    def fail_by_job_key(self, job_key: str, error: str, *, duration_s: float | None = None) -> None:
        task_id = self._by_job_key.get(job_key)
        if task_id:
            self.fail(task_id, error, duration_s=duration_s)

    def cancel_by_job_key(self, job_key: str) -> bool:
        task_id = self._by_job_key.get(job_key)
        if task_id:
            return self.cancel(task_id)
        return False

    def cancel(self, task_id: str) -> bool:
        record = self._tasks.get(task_id)
        if not record:
            return False
        if record.cancel_fn:
            try:
                record.cancel_fn()
            except Exception:
                pass
        record.status = "cancelled"
        record.updated_at = _utc_now()
        self._archive(record)
        return True

    def pause(self, task_id: str) -> bool:
        record = self._tasks.get(task_id)
        if not record:
            return False
        record.status = "paused"
        record.duration_s = None
        record.updated_at = _utc_now()
        return True

    def pause_by_job_key(self, job_key: str) -> bool:
        task_id = self._by_job_key.get(job_key)
        if task_id:
            return self.pause(task_id)
        return False

    def requeue(self, task_id: str) -> bool:
        record = self._tasks.get(task_id)
        if not record:
            return False
        record.status = "queued"
        record.updated_at = _utc_now()
        return True

    def requeue_by_job_key(self, job_key: str) -> bool:
        task_id = self._by_job_key.get(job_key)
        if task_id:
            return self.requeue(task_id)
        return False

    def _finish(self, task_id: str, status: TaskStatus) -> None:
        record = self._tasks.get(task_id)
        if not record:
            return
        record.status = status
        record.updated_at = _utc_now()
        self._archive(record)

    def _archive(self, record: TaskRecord) -> None:
        if record.job_key:
            self._by_job_key.pop(record.job_key, None)
        if record.status in ("completed", "failed", "cancelled"):
            if record.id not in self._completed:
                self._completed.append(record.id)

    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {
            "queued": 0,
            "running": 0,
            "paused": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
        }
        for record in self._tasks.values():
            counts[record.status] = counts.get(record.status, 0) + 1
        return counts

    def snapshot(
        self,
        *,
        status: TaskStatus | None = None,
        kind: TaskKind | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        records = list(self._tasks.values())
        if status:
            records = [r for r in records if r.status == status]
        if kind:
            records = [r for r in records if r.kind == kind]

        def sort_key(r: TaskRecord) -> tuple[int, str]:
            priority = {
                "running": 0,
                "queued": 1,
                "paused": 2,
                "failed": 3,
                "cancelled": 4,
                "completed": 5,
            }
            return (priority.get(r.status, 5), r.started_at)

        records.sort(key=sort_key)
        return [r.to_dict() for r in records[:limit]]
