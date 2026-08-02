"""Multi-book summarize concurrency integration tests."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import pytest

from lumina_core.config import ModelResource, ModelsConfig, ProfileRoute
from lumina_core.db.repos import BookRepo, SegmentRepo
from lumina_core.db.schema import init_db
from lumina_core.jobs.queue import JobQueue
from lumina_core.models.concurrency import ResourceConcurrencyGate
from lumina_core.models.router import ProfileModelRouter
from tests.support.mock_router import load_json_fixture

LLM_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "llm"
SUMMARY = load_json_fixture(LLM_FIXTURES / "summary_segment0.json")


def _ollama_models(*, concurrency: int = 1) -> ModelsConfig:
    return ModelsConfig(
        resources=[
            ModelResource(
                id="ollama",
                provider="ollama",
                base_url="http://127.0.0.1:11434",
                model="qwen3.5:4b",
                concurrency=concurrency,
            )
        ],
        summarize=ProfileRoute(priority=["ollama"]),
    )


def _seed_book(conn, *, book_id: str, n_segments: int = 3) -> str:
    BookRepo(conn).insert(
        id=book_id,
        title=f"Book {book_id}",
        format="txt",
        file_path="/tmp/t.txt",
        segment_count=n_segments,
        status="processing",
    )
    segs = [
        {
            "id": str(uuid.uuid4()),
            "book_id": book_id,
            "idx": i,
            "anchor_label": f"段 {i + 1}",
            "raw_text": f"正文段落 {book_id} {i}",
            "summary_status": "pending",
            "retry_count": 0,
        }
        for i in range(n_segments)
    ]
    SegmentRepo(conn).insert_many(segs)
    return book_id


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "multi_book_concurrency.db")


@pytest.mark.asyncio
async def test_multi_book_summarize_respects_ollama_concurrency(conn):
    models = _ollama_models(concurrency=1)
    gate = ResourceConcurrencyGate(models.resources)
    router = ProfileModelRouter(models, gate=gate)

    active = 0
    peak = 0
    lock = asyncio.Lock()
    response = json.dumps(SUMMARY, ensure_ascii=False)

    async def tracking_ollama(*args, **kwargs) -> str:
        nonlocal active, peak
        async with lock:
            active += 1
            peak = max(peak, active)
        try:
            await asyncio.sleep(0.08)
            return response
        finally:
            async with lock:
                active -= 1

    router._ollama_complete = tracking_ollama  # type: ignore[method-assign]

    q = JobQueue(conn, router)
    for book_id in ("book-a", "book-b", "book-c"):
        _seed_book(conn, book_id=book_id, n_segments=3)

    for book_id in ("book-a", "book-b", "book-c"):
        await q.enqueue_book_prefetch(book_id)

    for _ in range(120):
        all_ready = True
        for book_id in ("book-a", "book-b", "book-c"):
            segs = SegmentRepo(conn).list_for_book(book_id)
            if not segs or not all(s["summary_status"] == "ready" for s in segs):
                all_ready = False
                break
        if all_ready:
            break
        await asyncio.sleep(0.05)
    else:
        statuses = {
            bid: [s["summary_status"] for s in SegmentRepo(conn).list_for_book(bid)]
            for bid in ("book-a", "book-b", "book-c")
        }
        pytest.fail(f"segments not ready: {statuses}")

    assert peak <= 1
    runtime = router.gate.snapshot()
    ollama = next(r for r in runtime if r["resource_id"] == "ollama")
    assert ollama["limit"] == 1
    assert ollama["in_use"] == 0


@pytest.mark.asyncio
async def test_hot_update_preserves_concurrency_limit(conn):
    models = _ollama_models(concurrency=2)
    gate = ResourceConcurrencyGate(models.resources)
    router = ProfileModelRouter(models, gate=gate)

    active = 0
    peak = 0
    peak_after_update = 0
    lock = asyncio.Lock()
    update_done = asyncio.Event()
    response = json.dumps(SUMMARY, ensure_ascii=False)

    async def tracking_ollama(*args, **kwargs) -> str:
        nonlocal active, peak, peak_after_update
        async with lock:
            active += 1
            peak = max(peak, active)
            if update_done.is_set():
                peak_after_update = max(peak_after_update, active)
        try:
            await asyncio.sleep(0.06)
            return response
        finally:
            async with lock:
                active -= 1

    router._ollama_complete = tracking_ollama  # type: ignore[method-assign]

    q = JobQueue(conn, router)
    _seed_book(conn, book_id="book-a", n_segments=4)
    _seed_book(conn, book_id="book-b", n_segments=4)
    await q.enqueue_book_prefetch("book-a")
    await q.enqueue_book_prefetch("book-b")

    await asyncio.sleep(0.05)
    updated = _ollama_models(concurrency=1)
    router.models = updated
    router.update_resources(updated.resources)
    update_done.set()

    for _ in range(120):
        all_ready = True
        for book_id in ("book-a", "book-b"):
            segs = SegmentRepo(conn).list_for_book(book_id)
            if not segs or not all(s["summary_status"] == "ready" for s in segs):
                all_ready = False
                break
        if all_ready:
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("segments not ready after hot update")

    assert peak <= 2
    assert peak_after_update <= 1


@pytest.mark.asyncio
async def test_worker_target_uses_summarize_chain_primary(conn):
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
                base_url="https://cursor-proxy.example/v1",
                model="composer-2.5",
                api_key="test-key",
                concurrency=8,
            ),
        ],
        summarize=ProfileRoute(priority=["ollama", "cursor"]),
    )
    gate = ResourceConcurrencyGate(models.resources)
    router = ProfileModelRouter(models, gate=gate)
    q = JobQueue(conn, router)
    assert q._worker_target() == 1

    router.models = ModelsConfig(
        resources=models.resources,
        summarize=ProfileRoute(priority=["cursor", "ollama"]),
    )
    assert q._worker_target() == 8
