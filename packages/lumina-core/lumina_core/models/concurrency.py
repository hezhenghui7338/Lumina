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
        self._semaphores = self._build_semaphores(resources)
        self._in_use: dict[str, int] = {r.id: 0 for r in resources}
        self._limits: dict[str, int] = {
            r.id: effective_concurrency(r) for r in resources
        }

    def _build_semaphores(self, resources: list[ModelResource]) -> dict[str, asyncio.Semaphore]:
        semaphores: dict[str, asyncio.Semaphore] = {}
        for resource in resources:
            semaphores[resource.id] = asyncio.Semaphore(effective_concurrency(resource))
        return semaphores

    def set_resources(self, resources: list[ModelResource]) -> None:
        self._resources = list(resources)
        self._semaphores = self._build_semaphores(resources)
        self._in_use = {r.id: self._in_use.get(r.id, 0) for r in resources}
        self._limits = {r.id: effective_concurrency(r) for r in resources}

    @asynccontextmanager
    async def use(self, resource_id: str, *, skip_if_busy: bool = False):
        rid = resource_id.strip().lower()
        sem = self._semaphores.get(rid)
        if sem is None:
            sem = asyncio.Semaphore(1)
            self._semaphores[rid] = sem
            self._in_use.setdefault(rid, 0)
            self._limits.setdefault(rid, 1)
        if skip_if_busy and sem.locked():
            from lumina_core.debug_agent_log import agent_log

            agent_log(
                hypothesis_id="D",
                location="concurrency.py:use:busy",
                message="semaphore busy skip_if_busy",
                data={"resource_id": resource_id},
            )
            raise ResourceBusyError(f"{resource_id} busy")
        wait_started = time.time()
        await sem.acquire()
        waited_s = round(time.time() - wait_started, 2)
        if waited_s > 0.5:
            from lumina_core.debug_agent_log import agent_log

            agent_log(
                hypothesis_id="D",
                location="concurrency.py:use:acquired",
                message="semaphore acquired after wait",
                data={"resource_id": resource_id, "wait_s": waited_s},
            )
        self._in_use[rid] = self._in_use.get(rid, 0) + 1
        try:
            yield
        finally:
            self._in_use[rid] = max(0, self._in_use.get(rid, 1) - 1)
            sem.release()

    def snapshot(self) -> list[dict[str, int | str]]:
        rows: list[dict[str, int | str]] = []
        seen: set[str] = set()
        for resource in self._resources:
            rid = resource.id
            limit = self._limits.get(rid, effective_concurrency(resource))
            in_use = self._in_use.get(rid.lower(), self._in_use.get(rid, 0))
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
