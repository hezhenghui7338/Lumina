"""Per-resource concurrency gates for LLM resource calls."""

from __future__ import annotations

import asyncio
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

    def _build_semaphores(self, resources: list[ModelResource]) -> dict[str, asyncio.Semaphore]:
        semaphores: dict[str, asyncio.Semaphore] = {}
        for resource in resources:
            semaphores[resource.id] = asyncio.Semaphore(effective_concurrency(resource))
        return semaphores

    def set_resources(self, resources: list[ModelResource]) -> None:
        self._resources = list(resources)
        self._semaphores = self._build_semaphores(resources)

    @asynccontextmanager
    async def use(self, resource_id: str, *, skip_if_busy: bool = False):
        rid = resource_id.strip().lower()
        sem = self._semaphores.get(rid)
        if sem is None:
            sem = asyncio.Semaphore(1)
            self._semaphores[rid] = sem
        if skip_if_busy and sem.locked():
            raise ResourceBusyError(f"{resource_id} busy")
        await sem.acquire()
        try:
            yield
        finally:
            sem.release()

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
