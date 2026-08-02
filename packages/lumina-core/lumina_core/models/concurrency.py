"""Per-resource concurrency gates for LLM resource calls."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from lumina_core.config import ModelResource, effective_concurrency


class ResourceBusyError(Exception):
    """Raised when a resource slot is full and skip_if_busy is enabled."""


class ResourceConcurrencyGate:
    """Global semaphores shared by chat, summarize, and translate (keyed by resource id)."""

    def __init__(self, resources: list[ModelResource]) -> None:
        self._resources = list(resources)
        self._limits: dict[str, int] = {
            r.id: effective_concurrency(r) for r in resources
        }
        self._in_use: dict[str, int] = {r.id: 0 for r in resources}
        self._conditions: dict[str, asyncio.Condition] = {
            r.id: asyncio.Condition() for r in resources
        }

    def _ensure_resource(self, rid: str, *, default_limit: int = 1) -> asyncio.Condition:
        self._limits.setdefault(rid, default_limit)
        self._in_use.setdefault(rid, 0)
        if rid not in self._conditions:
            self._conditions[rid] = asyncio.Condition()
        return self._conditions[rid]

    def set_resources(self, resources: list[ModelResource]) -> None:
        """Hot-update resource limits while preserving in-flight slot counts."""
        self._resources = list(resources)
        seen: set[str] = set()
        for resource in resources:
            rid = resource.id
            seen.add(rid)
            new_limit = effective_concurrency(resource)
            old_limit = self._limits.get(rid, new_limit)
            self._limits[rid] = new_limit
            self._in_use.setdefault(rid, 0)
            cond = self._ensure_resource(rid, default_limit=new_limit)
            if new_limit > old_limit:
                # Wake waiters that may now acquire under the higher limit.
                cond.notify(new_limit - old_limit)
        # Drop stale resource ids no longer in config (keep counters for safety).
        for rid in list(self._limits.keys()):
            if rid not in seen:
                del self._limits[rid]

    @asynccontextmanager
    async def use(self, resource_id: str, *, skip_if_busy: bool = False):
        rid = resource_id.strip().lower()
        limit = self._limits.get(rid, 1)
        cond = self._ensure_resource(rid, default_limit=limit)
        if skip_if_busy:
            async with cond:
                if self._in_use.get(rid, 0) >= limit:
                    from lumina_core.debug_agent_log import agent_log

                    agent_log(
                        hypothesis_id="D",
                        location="concurrency.py:use:busy",
                        message="semaphore busy skip_if_busy",
                        data={"resource_id": resource_id},
                    )
                    raise ResourceBusyError(f"{resource_id} busy")
        wait_started = time.time()
        async with cond:
            while self._in_use.get(rid, 0) >= self._limits.get(rid, limit):
                await cond.wait()
            self._in_use[rid] = self._in_use.get(rid, 0) + 1
        waited_s = round(time.time() - wait_started, 2)
        if waited_s > 0.5:
            from lumina_core.debug_agent_log import agent_log

            agent_log(
                hypothesis_id="D",
                location="concurrency.py:use:acquired",
                message="semaphore acquired after wait",
                data={"resource_id": resource_id, "wait_s": waited_s},
            )
        try:
            yield
        finally:
            async with cond:
                self._in_use[rid] = max(0, self._in_use.get(rid, 1) - 1)
                cond.notify()

    def snapshot(self) -> list[dict[str, int | str]]:
        rows: list[dict[str, int | str]] = []
        seen: set[str] = set()
        for resource in self._resources:
            rid = resource.id
            limit = self._limits.get(rid, effective_concurrency(resource))
            in_use = self._in_use.get(rid, 0)
            rows.append(
                {
                    "resource_id": rid,
                    "limit": limit,
                    "in_use": in_use,
                    "available": max(0, limit - in_use),
                }
            )
            seen.add(rid)
        for rid, limit in self._limits.items():
            if rid in seen:
                continue
            in_use = self._in_use.get(rid, 0)
            rows.append(
                {
                    "resource_id": rid,
                    "limit": limit,
                    "in_use": in_use,
                    "available": max(0, limit - in_use),
                }
            )
        return rows

    async def wrap_stream(
        self,
        resource_id: str,
        stream: AsyncIterator[str],
        *,
        skip_if_busy: bool = False,
    ) -> AsyncIterator[str]:
        async with self.use(resource_id, skip_if_busy=skip_if_busy):
            async for chunk in stream:
                yield chunk
