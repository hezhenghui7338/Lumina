"""Helpers for registering LLM tasks in TaskRegistry."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any, TypeVar

from lumina_core.db.repos import BookRepo
from lumina_core.ops.task_registry import TaskKind, TaskRecord, TaskRegistry

T = TypeVar("T")


def book_title(conn, book_id: str) -> str:
    book = BookRepo(conn).get(book_id)
    return (book or {}).get("title") or book_id


def register_book_task(
    registry: TaskRegistry,
    *,
    kind: TaskKind,
    book_id: str,
    subject_label: str,
    detail: str,
    profile: str | None = None,
    cancellable: bool = False,
    cancel_fn: Callable[[], None] | None = None,
    status: str = "queued",
) -> TaskRecord:
    return registry.register(
        kind=kind,
        subject_type="book",
        subject_id=book_id,
        subject_label=subject_label,
        detail=detail,
        profile=profile,
        cancellable=cancellable,
        cancel_fn=cancel_fn,
        status=status,  # type: ignore[arg-type]
    )


def register_article_task(
    registry: TaskRegistry,
    *,
    kind: TaskKind,
    article_id: str,
    subject_label: str,
    detail: str,
    profile: str | None = None,
    cancellable: bool = False,
    cancel_fn: Callable[[], None] | None = None,
    status: str = "running",
) -> TaskRecord:
    return registry.register(
        kind=kind,
        subject_type="article",
        subject_id=article_id,
        subject_label=subject_label,
        detail=detail,
        profile=profile,
        cancellable=cancellable,
        cancel_fn=cancel_fn,
        status=status,  # type: ignore[arg-type]
    )


async def track_async_task(
    registry: TaskRegistry,
    record: TaskRecord,
    coro: Coroutine[Any, Any, T],
    router_resource: Callable[[], str | None] | None = None,
) -> T:
    registry.mark_running(record.id)
    try:
        result = await coro
        if router_resource:
            registry.update_resource(record.id, router_resource())
        registry.complete(record.id)
        return result
    except asyncio.CancelledError:
        registry.cancel(record.id)
        raise
    except Exception as exc:
        registry.fail(record.id, str(exc))
        raise


async def track_stream_events(
    registry: TaskRegistry,
    record: TaskRecord,
    stream: AsyncIterator[dict[str, Any]],
    *,
    cancel_event: asyncio.Event,
    router_resource: Callable[[], str | None] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    registry.mark_running(record.id)
    cancelled = False
    try:
        async for event in stream:
            if cancel_event.is_set():
                cancelled = True
                break
            yield event
    except asyncio.CancelledError:
        cancelled = True
        raise
    except Exception as exc:
        registry.fail(record.id, str(exc))
        raise
    finally:
        if cancelled or cancel_event.is_set():
            registry.cancel(record.id)
        else:
            if router_resource:
                registry.update_resource(record.id, router_resource())
            registry.complete(record.id)
