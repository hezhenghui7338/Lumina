"""Resource concurrency gate tests."""

from __future__ import annotations

import asyncio

import pytest

from lumina_core.config import (
    ModelResource,
    ModelsConfig,
    ProfileRoute,
    default_concurrency_for_provider,
    effective_concurrency,
    migrate_job_concurrency_to_resources,
    normalize_models_raw,
)
from lumina_core.models.concurrency import ResourceBusyError, ResourceConcurrencyGate
from lumina_core.models.router import ProfileModelRouter


def _resources(*items: ModelResource) -> list[ModelResource]:
    return list(items)


@pytest.mark.asyncio
async def test_gate_ollama_skip_when_busy():
    resources = [
        ModelResource(id="ollama", provider="ollama", base_url="http://127.0.0.1:11434", model="m", concurrency=2),
    ]
    gate = ResourceConcurrencyGate(resources)
    acquired: list[int] = []

    async def hold_slot(slot: int) -> None:
        async with gate.use("ollama"):
            acquired.append(slot)
            await asyncio.sleep(0.2)

    t1 = asyncio.create_task(hold_slot(1))
    t2 = asyncio.create_task(hold_slot(2))
    await asyncio.sleep(0.05)

    with pytest.raises(ResourceBusyError):
        async with gate.use("ollama", skip_if_busy=True):
            pass

    await asyncio.gather(t1, t2)
    assert sorted(acquired) == [1, 2]


@pytest.mark.asyncio
async def test_gate_cursor_allows_eight_parallel():
    resources = [
        ModelResource(id="cursor", provider="cursor", model="composer-2.5", concurrency=8),
    ]
    gate = ResourceConcurrencyGate(resources)
    active = 0
    peak = 0
    lock = asyncio.Lock()

    async def worker() -> None:
        nonlocal active, peak
        async with gate.use("cursor"):
            async with lock:
                active += 1
                peak = max(peak, active)
            await asyncio.sleep(0.05)
            async with lock:
                active -= 1

    await asyncio.gather(*(worker() for _ in range(8)))
    assert peak == 8


@pytest.mark.asyncio
async def test_gate_same_provider_resources_are_independent():
    resources = [
        ModelResource(id="openrouter-a", provider="openrouter", model="m1", concurrency=1),
        ModelResource(id="openrouter-b", provider="openrouter", model="m2", concurrency=1),
    ]
    gate = ResourceConcurrencyGate(resources)

    async def hold(resource_id: str) -> None:
        async with gate.use(resource_id):
            await asyncio.sleep(0.15)

    t1 = asyncio.create_task(hold("openrouter-a"))
    await asyncio.sleep(0.02)
    async with gate.use("openrouter-b"):
        pass
    await t1


@pytest.mark.asyncio
async def test_router_ollama_busy_falls_back_to_cursor():
    models = ModelsConfig(
        resources=[
            ModelResource(
                id="ollama",
                provider="ollama",
                base_url="http://127.0.0.1:11434",
                model="m",
                concurrency=1,
            ),
            ModelResource(
                id="cursor",
                provider="cursor",
                model="composer-2.5",
                api_key="test-key",
                concurrency=8,
            ),
        ],
        summarize=ProfileRoute(priority=["ollama", "cursor"]),
    )
    router = ProfileModelRouter(models)

    async def slow_ollama(*args, **kwargs) -> str:
        await asyncio.sleep(0.3)
        return "ollama-response"

    async def cursor_complete(*args, **kwargs) -> str:
        return "cursor-response"

    router._ollama_complete = slow_ollama  # type: ignore[method-assign]
    router._cursor_complete = cursor_complete  # type: ignore[method-assign]

    first = asyncio.create_task(router.complete("prompt-a", profile="summarize"))
    await asyncio.sleep(0.02)
    second = await router.complete("prompt-b", profile="summarize")

    assert second == "cursor-response"
    assert router.last_resource_id == "cursor"
    await first


def test_effective_concurrency_defaults():
    ollama = ModelResource(id="ollama", provider="ollama", base_url="http://127.0.0.1:11434", model="m")
    cursor = ModelResource(id="cursor", provider="cursor", model="composer-2.5")
    openai = ModelResource(id="openai", provider="openai", base_url="https://api.openai.com/v1", model="gpt")

    assert effective_concurrency(ollama) == 2
    assert effective_concurrency(cursor) == 8
    assert effective_concurrency(openai) == 4
    assert default_concurrency_for_provider("openrouter") == 4


def test_max_concurrency_for_profile_mixed_chain():
    models = ModelsConfig(
        summarize=ProfileRoute(priority=["ollama", "cursor", "openrouter"]),
    )
    assert models.max_concurrency_for_profile("summarize") == 8


def test_migrate_job_concurrency_to_resources():
    raw = {
        "resources": [
            {"id": "ollama", "provider": "ollama", "model": "m"},
            {"id": "openai", "provider": "openai", "model": "gpt"},
        ],
        "job_concurrency": {"ollama": 3, "cloud": 6},
    }
    migrated = normalize_models_raw(raw)
    assert "job_concurrency" not in migrated
    by_id = {r["id"]: r for r in migrated["resources"]}
    assert by_id["ollama"]["concurrency"] == 3
    assert by_id["openai"]["concurrency"] == 6


def test_migrate_preserves_existing_resource_concurrency():
    raw = {
        "resources": [{"id": "ollama", "provider": "ollama", "model": "m", "concurrency": 1}],
        "job_concurrency": {"ollama": 5},
    }
    migrated = migrate_job_concurrency_to_resources(raw)
    assert migrated["resources"][0]["concurrency"] == 1
