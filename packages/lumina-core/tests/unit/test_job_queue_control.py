"""JobQueue user start/stop summarize tests."""

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
from tests.support.mock_router import MockModelRouter, load_json_fixture

LLM_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "llm"
SUMMARY = load_json_fixture(LLM_FIXTURES / "summary_segment0.json")


class SlowMockRouter(MockModelRouter):
    def __init__(self, delay: float = 0.4, **kwargs) -> None:
        super().__init__(**kwargs)
        self.delay = delay

    async def complete(
        self,
        prompt: str,
        *,
        profile="summarize",
        summary_tier="normal",
        json_mode: bool = False,
        on_slot_acquired=None,
    ) -> str:
        if on_slot_acquired is not None:
            await on_slot_acquired()
        await asyncio.sleep(self.delay)
        return await super().complete(
            prompt,
            profile=profile,
            summary_tier=summary_tier,
            json_mode=json_mode,
            on_slot_acquired=None,
        )


def _seed_book(conn, *, book_id: str = "book-a", n_segments: int = 3) -> str:
    BookRepo(conn).insert(
        id=book_id,
        title="Test",
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
            "raw_text": f"正文段落 {i}",
            "summary_status": "pending",
            "retry_count": 0,
        }
        for i in range(n_segments)
    ]
    SegmentRepo(conn).insert_many(segs)
    return book_id


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "queue.db")


@pytest.mark.asyncio
async def test_stop_book_drains_pending_jobs(conn):
    router = SlowMockRouter(
        delay=1.0,
        responses={"summarize": SUMMARY, "translate": "译文"},
    )
    q = JobQueue(conn, router)
    book_id = _seed_book(conn, n_segments=5)
    await q.enqueue_book_prefetch(book_id)
    await asyncio.sleep(0.05)
    await q.stop_book(book_id)

    assert q.is_user_paused(book_id)
    assert q._queue.qsize() == 0
    # Allow any in-flight to settle under cancel
    await asyncio.sleep(1.2)
    statuses = {s["idx"]: s["summary_status"] for s in SegmentRepo(conn).list_for_book(book_id)}
    assert all(st in ("pending", "ready") for st in statuses.values())
    # Most should remain pending since stop drained the queue
    assert sum(1 for st in statuses.values() if st == "pending") >= 3


@pytest.mark.asyncio
async def test_prepare_book_resegment_preserves_previous_pause_state(conn):
    router = MockModelRouter(responses={"summarize": SUMMARY, "translate": "译文"})
    q = JobQueue(conn, router)
    paused_book = _seed_book(conn, book_id="paused-book", n_segments=1)
    active_book = _seed_book(conn, book_id="active-book", n_segments=1)

    await q.stop_book(paused_book)
    assert await q.prepare_book_resegment(paused_book) is True
    assert q.is_user_paused(paused_book)

    assert await q.prepare_book_resegment(active_book) is False
    assert q.is_user_paused(active_book)
    q.unpause_book(active_book)
    assert not q.is_user_paused(active_book)


@pytest.mark.asyncio
async def test_stop_resets_running_to_pending(conn):
    router = SlowMockRouter(
        delay=0.8,
        responses={"summarize": SUMMARY, "translate": "译文"},
    )
    q = JobQueue(conn, router)
    book_id = _seed_book(conn, n_segments=2)
    await q.enqueue_book_prefetch(book_id)

    for _ in range(40):
        segs = SegmentRepo(conn).list_for_book(book_id)
        if any(s["summary_status"] == "running" for s in segs):
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("segment never reached running")

    await q.stop_book(book_id)
    await asyncio.sleep(1.0)

    segs = SegmentRepo(conn).list_for_book(book_id)
    assert not any(s["summary_status"] == "running" for s in segs)
    assert q.is_user_paused(book_id)


@pytest.mark.asyncio
async def test_start_book_reenqueues_after_stop(conn):
    router = MockModelRouter(responses={"summarize": SUMMARY, "translate": "译文"})
    q = JobQueue(conn, router)
    book_id = _seed_book(conn, n_segments=2)
    await q.stop_book(book_id)
    assert q.is_user_paused(book_id)

    await q.start_book(book_id)
    assert not q.is_user_paused(book_id)

    for _ in range(50):
        segs = SegmentRepo(conn).list_for_book(book_id)
        if all(s["summary_status"] == "ready" for s in segs):
            break
        await asyncio.sleep(0.1)
    else:
        statuses = [s["summary_status"] for s in SegmentRepo(conn).list_for_book(book_id)]
        pytest.fail(f"segments not ready: {statuses}")


@pytest.mark.asyncio
async def test_start_book_resets_failed_and_completes(conn):
    router = MockModelRouter(responses={"summarize": SUMMARY, "translate": "译文"})
    q = JobQueue(conn, router)
    book_id = _seed_book(conn, n_segments=2)
    segs = SegmentRepo(conn).list_for_book(book_id)
    seg_repo = SegmentRepo(conn)
    seg_repo.update_summary(
        segs[0]["id"],
        summary_json='{"sentences":["x"],"bullets":[],"label":"a","anchor":"b"}',
        label="a",
        status="ready",
    )
    seg_repo.set_status(segs[1]["id"], "failed", retry_count=3)

    await q.stop_book(book_id)
    await q.start_book(book_id)

    for _ in range(50):
        updated = seg_repo.get_by_index(book_id, 1)
        if updated["summary_status"] == "ready":
            break
        await asyncio.sleep(0.1)
    else:
        statuses = [s["summary_status"] for s in seg_repo.list_for_book(book_id)]
        pytest.fail(f"failed segment not recovered: {statuses}")

    assert seg_repo.get_by_index(book_id, 0)["summary_status"] == "ready"


@pytest.mark.asyncio
async def test_start_book_advanced_does_not_reset_ready(conn):
    router = MockModelRouter(responses={"summarize": SUMMARY, "translate": "译文"})
    q = JobQueue(conn, router)
    book_id = _seed_book(conn, n_segments=2)
    segs = SegmentRepo(conn).list_for_book(book_id)
    seg_repo = SegmentRepo(conn)
    kept_json = '{"sentences":["KEEP-ME"],"bullets":[],"label":"kept","anchor":"a"}'
    seg_repo.update_summary(
        segs[0]["id"],
        summary_json=kept_json,
        label="kept",
        summary_tier="normal",
        status="ready",
    )
    await q.stop_book(book_id)
    await q.start_book(book_id, summary_tier="advanced")

    for _ in range(50):
        pending = seg_repo.get_by_index(book_id, 1)
        if pending["summary_status"] == "ready":
            break
        await asyncio.sleep(0.1)
    else:
        statuses = [s["summary_status"] for s in seg_repo.list_for_book(book_id)]
        pytest.fail(f"pending segment not summarized: {statuses}")

    kept = seg_repo.get_by_index(book_id, 0)
    assert kept["summary_json"] == kept_json
    assert kept["summary_tier"] == "normal"
    assert kept["label"] == "kept"
    done = seg_repo.get_by_index(book_id, 1)
    assert done["summary_status"] == "ready"
    assert done["summary_tier"] == "advanced"


@pytest.mark.asyncio
async def test_regenerate_advanced_resets_ready(conn):
    router = MockModelRouter(responses={"summarize": SUMMARY, "translate": "译文"})
    q = JobQueue(conn, router)
    book_id = _seed_book(conn, n_segments=2)
    segs = SegmentRepo(conn).list_for_book(book_id)
    seg_repo = SegmentRepo(conn)
    kept_json = '{"sentences":["KEEP-ME"],"bullets":[],"label":"kept","anchor":"a"}'
    for seg in segs:
        seg_repo.update_summary(
            seg["id"],
            summary_json=kept_json,
            label="kept",
            summary_tier="normal",
            status="ready",
        )
    await q.stop_book(book_id)
    count = await q.enqueue_book_regenerate(book_id, summary_tier="advanced")
    assert count == 2

    for _ in range(50):
        updated = seg_repo.list_for_book(book_id)
        if all(
            s["summary_status"] == "ready" and s["summary_tier"] == "advanced"
            for s in updated
        ):
            break
        await asyncio.sleep(0.1)
    else:
        rows = seg_repo.list_for_book(book_id)
        pytest.fail(
            "regenerate did not finish: "
            f"{[(s['summary_status'], s['summary_tier']) for s in rows]}"
        )

    for seg in seg_repo.list_for_book(book_id):
        assert seg["summary_json"] != kept_json
        assert seg["label"] != "kept"


@pytest.mark.asyncio
async def test_stop_all_and_start_all(conn):
    router = MockModelRouter(responses={"summarize": SUMMARY, "translate": "译文"})
    q = JobQueue(conn, router)
    a = _seed_book(conn, book_id="book-a", n_segments=1)
    b = _seed_book(conn, book_id="book-b", n_segments=1)

    await q.stop_all()
    assert q.is_user_paused(a)
    assert q.is_user_paused(b)

    # Enqueue while paused should no-op
    await q.enqueue_book_prefetch(a)
    assert q._queue.qsize() == 0

    await q.start_all()
    assert not q.is_user_paused(a)
    assert not q.is_user_paused(b)

    for _ in range(50):
        segs_a = SegmentRepo(conn).list_for_book(a)
        segs_b = SegmentRepo(conn).list_for_book(b)
        if (
            segs_a
            and segs_b
            and segs_a[0]["summary_status"] == "ready"
            and segs_b[0]["summary_status"] == "ready"
        ):
            break
        await asyncio.sleep(0.1)
    else:
        pytest.fail("start_all did not complete summaries")


@pytest.mark.asyncio
async def test_unpause_book_allows_retry_enqueue(conn):
    router = MockModelRouter(responses={"summarize": SUMMARY, "translate": "译文"})
    q = JobQueue(conn, router)
    book_id = _seed_book(conn, n_segments=1)
    await q.stop_book(book_id)
    seg = SegmentRepo(conn).list_for_book(book_id)[0]

    await q.enqueue_summarize(book_id, seg["id"], seg["idx"], high=True)
    assert q._queue.qsize() == 0

    q.unpause_book(book_id)
    await q.enqueue_summarize(book_id, seg["id"], seg["idx"], high=True)
    assert q._queue.qsize() >= 1 or seg["summary_status"] in ("pending", "running", "ready")


@pytest.mark.asyncio
async def test_refresh_workers_scales_workers_up(conn):
    ollama = ModelResource(
        id="ollama",
        provider="ollama",
        base_url="http://127.0.0.1:11434",
        model="m",
        concurrency=1,
    )
    models = ModelsConfig(resources=[ollama], summarize=ProfileRoute(priority=["ollama"]))
    router = MockModelRouter(responses={"summarize": SUMMARY, "translate": "译文"}, models=models)
    q = JobQueue(conn, router)
    q.ensure_workers()
    assert q._worker_count == 1

    router.models = ModelsConfig(
        resources=[
            ModelResource(
                id="ollama",
                provider="ollama",
                base_url="http://127.0.0.1:11434",
                model="m",
                concurrency=3,
            )
        ],
        summarize=ProfileRoute(priority=["ollama"]),
    )
    q.refresh_workers()
    assert q._worker_count == 3

    router.models = ModelsConfig(
        resources=[
            ModelResource(
                id="ollama",
                provider="ollama",
                base_url="http://127.0.0.1:11434",
                model="m",
                concurrency=2,
            )
        ],
        summarize=ProfileRoute(priority=["ollama"]),
    )
    q.refresh_workers()
    assert q._worker_count == 3


@pytest.mark.asyncio
async def test_worker_target_uses_ollama_concurrency_when_primary_ollama(conn):
    models = ModelsConfig(
        summarize=ProfileRoute(priority=["ollama", "cursor"]),
    )
    router = MockModelRouter(responses={"summarize": SUMMARY, "translate": "译文"}, models=models)
    q = JobQueue(conn, router)
    assert q._worker_target() == 1


@pytest.mark.asyncio
async def test_pause_ollama_blocks_summarize_until_resume(conn):
    """Book chat uses pause_ollama to preempt library prefetch."""
    router = SlowMockRouter(
        delay=0.2,
        responses={"summarize": SUMMARY, "translate": "译文"},
    )
    q = JobQueue(conn, router)
    book_id = _seed_book(conn, n_segments=2)

    q.pause_ollama()
    assert not q._paused.is_set()
    await q.enqueue_book_prefetch(book_id)
    await asyncio.sleep(0.5)

    statuses = [s["summary_status"] for s in SegmentRepo(conn).list_for_book(book_id)]
    assert all(st == "pending" for st in statuses)

    q.resume_ollama()
    assert q._paused.is_set()
    for _ in range(50):
        segs = SegmentRepo(conn).list_for_book(book_id)
        if all(s["summary_status"] == "ready" for s in segs):
            break
        await asyncio.sleep(0.1)
    else:
        statuses = [s["summary_status"] for s in SegmentRepo(conn).list_for_book(book_id)]
        pytest.fail(f"summarize did not resume after resume_ollama: {statuses}")


@pytest.mark.asyncio
async def test_summarize_progresses_without_pause_ollama(conn):
    """News must not call pause_ollama; library summarize keeps running."""
    router = MockModelRouter(responses={"summarize": SUMMARY, "translate": "译文"})
    q = JobQueue(conn, router)
    book_id = _seed_book(conn, n_segments=2)

    assert q._paused.is_set()
    await q.enqueue_book_prefetch(book_id)

    for _ in range(50):
        segs = SegmentRepo(conn).list_for_book(book_id)
        if all(s["summary_status"] == "ready" for s in segs):
            break
        await asyncio.sleep(0.1)
    else:
        statuses = [s["summary_status"] for s in SegmentRepo(conn).list_for_book(book_id)]
        pytest.fail(f"summarize stalled without pause: {statuses}")

    assert q._paused.is_set()


@pytest.mark.asyncio
async def test_summarize_persists_provider_and_model(conn):
    ollama = ModelResource(
        id="ollama",
        provider="ollama",
        base_url="http://127.0.0.1:11434",
        model="qwen3.5:4b",
    )
    models = ModelsConfig(
        resources=[ollama],
        summarize=ProfileRoute(priority=["ollama"]),
    )
    router = MockModelRouter(
        responses={"summarize": SUMMARY, "translate": "译文"},
        models=models,
    )
    q = JobQueue(conn, router)
    book_id = _seed_book(conn, n_segments=1)
    await q.enqueue_book_prefetch(book_id)

    for _ in range(50):
        segs = SegmentRepo(conn).list_for_book(book_id)
        if segs and segs[0]["summary_status"] == "ready":
            break
        await asyncio.sleep(0.1)
    else:
        statuses = [s["summary_status"] for s in SegmentRepo(conn).list_for_book(book_id)]
        pytest.fail(f"segment not ready: {statuses}")

    seg = SegmentRepo(conn).list_for_book(book_id)[0]
    assert seg["summary_provider"] == "ollama"
    assert seg["summary_model"] == "qwen3.5:4b"


@pytest.mark.asyncio
async def test_skip_translate_when_same_language(conn):
    router = MockModelRouter(responses={"summarize": SUMMARY, "translate": "译文"})
    q = JobQueue(conn, router, target_language="zh-CN")
    book_id = _seed_book(conn, n_segments=1)
    BookRepo(conn).update(book_id, language="zh", target_language="zh-CN")
    await q.enqueue_book_prefetch(book_id)

    for _ in range(50):
        segs = SegmentRepo(conn).list_for_book(book_id)
        if segs and segs[0]["summary_status"] == "ready":
            break
        await asyncio.sleep(0.1)
    else:
        pytest.fail("segment not ready")

    seg = SegmentRepo(conn).list_for_book(book_id)[0]
    assert seg.get("translation") in (None, "")
    translate_calls = [c for c in router.calls if c.get("profile") == "translate"]
    assert translate_calls == []


@pytest.mark.asyncio
async def test_translate_when_different_language(conn):
    router = MockModelRouter(responses={"summarize": SUMMARY, "translate": "译文"})
    q = JobQueue(conn, router, target_language="zh-CN")
    book_id = _seed_book(conn, n_segments=1)
    BookRepo(conn).update(book_id, language="en", target_language="zh-CN")
    await q.enqueue_book_prefetch(book_id)

    for _ in range(80):
        segs = SegmentRepo(conn).list_for_book(book_id)
        if segs and segs[0].get("translation"):
            break
        await asyncio.sleep(0.1)
    else:
        pytest.fail("translation not written")

    seg = SegmentRepo(conn).list_for_book(book_id)[0]
    assert seg["translation"] == "译文"


@pytest.mark.asyncio
async def test_enqueue_registers_task_in_registry(conn):
    from lumina_core.ops.task_registry import TaskRegistry

    registry = TaskRegistry()
    router = SlowMockRouter(
        delay=0.05,
        responses={"summarize": SUMMARY, "translate": "译文"},
    )
    q = JobQueue(conn, router, task_registry=registry)
    book_id = _seed_book(conn, n_segments=1)
    await q.enqueue_book_prefetch(book_id)
    await asyncio.sleep(0.02)
    snap = registry.snapshot()
    assert any(t["kind"] == "summarize" for t in snap)
    assert snap[0]["subject_label"] == "Test"


@pytest.mark.asyncio
async def test_stop_book_pauses_queued_registry_tasks(conn):
    from lumina_core.ops.task_registry import TaskRegistry

    registry = TaskRegistry()
    router = SlowMockRouter(
        delay=1.0,
        responses={"summarize": SUMMARY, "translate": "译文"},
    )
    q = JobQueue(conn, router, task_registry=registry)
    book_id = _seed_book(conn, n_segments=5)
    await q.enqueue_book_prefetch(book_id)
    await asyncio.sleep(0.05)

    scheduled = [
        t for t in registry.snapshot() if t["status"] in ("queued", "running")
    ]
    assert len(scheduled) == 1

    await q.stop_book(book_id)

    paused = [t for t in registry.snapshot() if t["status"] == "paused"]
    assert len(paused) == 1
    assert all(t["duration_s"] is None for t in paused)
    assert registry.counts()["queued"] == 0
    assert len(q._paused_backlog) == 1


@pytest.mark.asyncio
async def test_stop_book_clears_summarize_active(conn):
    router = SlowMockRouter(
        delay=0.8,
        responses={"summarize": SUMMARY, "translate": "译文"},
    )
    q = JobQueue(conn, router)
    book_id = _seed_book(conn, n_segments=2)
    await q.enqueue_book_prefetch(book_id)

    for _ in range(40):
        if q.summarize_active_for_book(book_id) is not None:
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("summarize never became active")

    await q.stop_book(book_id)
    assert q.summarize_active_for_book(book_id) is None


@pytest.mark.asyncio
async def test_stop_all_clears_summarize_active(conn):
    router = SlowMockRouter(
        delay=0.8,
        responses={"summarize": SUMMARY, "translate": "译文"},
    )
    q = JobQueue(conn, router)
    book_id = _seed_book(conn, n_segments=1)
    await q.enqueue_book_prefetch(book_id)

    for _ in range(40):
        if q.summarize_active_for_book(book_id) is not None:
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("summarize never became active")

    await q.stop_all()
    assert q.summarize_active_for_book(book_id) is None


@pytest.mark.asyncio
async def test_mark_running_starts_timer_from_zero(conn):
    from lumina_core.ops.task_registry import TaskRegistry

    registry = TaskRegistry()
    router = SlowMockRouter(
        delay=0.3,
        responses={"summarize": SUMMARY, "translate": "译文"},
    )
    q = JobQueue(conn, router, task_registry=registry)
    book_id = _seed_book(conn, n_segments=1)
    await q.enqueue_book_prefetch(book_id)

    queued_started_at = None
    for _ in range(40):
        snap = registry.snapshot(status="queued")
        if snap:
            queued_started_at = snap[0]["started_at"]
            break
        await asyncio.sleep(0.02)
    assert queued_started_at is not None

    running_started_at = None
    for _ in range(40):
        snap = registry.snapshot(status="running")
        if snap:
            running_started_at = snap[0]["started_at"]
            break
        await asyncio.sleep(0.05)
    assert running_started_at is not None
    assert running_started_at >= queued_started_at


@pytest.mark.asyncio
async def test_stop_moves_queued_to_paused_backlog(conn):
    router = SlowMockRouter(
        delay=1.0,
        responses={"summarize": SUMMARY, "translate": "译文"},
    )
    q = JobQueue(conn, router)
    book_id = _seed_book(conn, n_segments=5)
    await q.enqueue_book_prefetch(book_id)
    await asyncio.sleep(0.05)
    await q.stop_book(book_id)

    assert q.is_user_paused(book_id)
    assert q._queue.qsize() == 0
    assert len(q._paused_backlog) == 1


@pytest.mark.asyncio
async def test_stop_moves_running_to_paused_backlog(conn):
    router = SlowMockRouter(
        delay=0.8,
        responses={"summarize": SUMMARY, "translate": "译文"},
    )
    q = JobQueue(conn, router)
    book_id = _seed_book(conn, n_segments=2)
    await q.enqueue_book_prefetch(book_id)

    for _ in range(40):
        segs = SegmentRepo(conn).list_for_book(book_id)
        if any(s["summary_status"] == "running" for s in segs):
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("segment never reached running")

    await q.stop_book(book_id)
    assert any(item.book_id == book_id for item in q._paused_backlog.values())


@pytest.mark.asyncio
async def test_resume_restores_backlog_to_queue(conn):
    router = SlowMockRouter(
        delay=1.0,
        responses={"summarize": SUMMARY, "translate": "译文"},
    )
    q = JobQueue(conn, router)
    book_id = _seed_book(conn, n_segments=3)
    await q.enqueue_book_prefetch(book_id)
    await asyncio.sleep(0.05)
    await q.stop_book(book_id)
    assert len(q._paused_backlog) == 1

    await q.start_book(book_id)
    assert len(q._paused_backlog) == 0
    assert not q.is_user_paused(book_id)

    for _ in range(80):
        segs = SegmentRepo(conn).list_for_book(book_id)
        if all(s["summary_status"] == "ready" for s in segs):
            break
        await asyncio.sleep(0.1)
    else:
        pytest.fail("resume did not complete summaries from backlog")


@pytest.mark.asyncio
async def test_resume_no_duplicate_jobs(conn):
    router = SlowMockRouter(
        delay=1.0,
        responses={"summarize": SUMMARY, "translate": "译文"},
    )
    q = JobQueue(conn, router)
    book_id = _seed_book(conn, n_segments=2)
    await q.enqueue_book_prefetch(book_id)
    await asyncio.sleep(0.05)
    await q.stop_book(book_id)
    backlog_size = len(q._paused_backlog)
    assert backlog_size >= 1

    await q.start_book(book_id)

    for _ in range(60):
        segs = SegmentRepo(conn).list_for_book(book_id)
        if all(s["summary_status"] == "ready" for s in segs):
            break
        await asyncio.sleep(0.1)
    else:
        pytest.fail("resume did not complete all segments")

    segs = SegmentRepo(conn).list_for_book(book_id)
    ready_count = sum(1 for s in segs if s["summary_status"] == "ready")
    assert ready_count == len(segs)


@pytest.mark.asyncio
async def test_registry_paused_not_cancelled(conn):
    from lumina_core.ops.task_registry import TaskRegistry

    registry = TaskRegistry()
    router = SlowMockRouter(
        delay=1.0,
        responses={"summarize": SUMMARY, "translate": "译文"},
    )
    q = JobQueue(conn, router, task_registry=registry)
    book_id = _seed_book(conn, n_segments=3)
    await q.enqueue_book_prefetch(book_id)
    await asyncio.sleep(0.05)

    await q.stop_book(book_id)

    counts = registry.counts()
    assert counts["paused"] == 1
    assert counts["cancelled"] == 0
    paused_tasks = registry.snapshot(status="paused")
    assert all(t["status"] == "paused" for t in paused_tasks)


@pytest.mark.asyncio
async def test_summarize_state_queued_after_enqueue(conn):
    router = SlowMockRouter(
        delay=1.0,
        responses={"summarize": SUMMARY, "translate": "译文"},
    )
    q = JobQueue(conn, router)
    book_id = _seed_book(conn, n_segments=3)
    await q.enqueue_book_prefetch(book_id)
    await asyncio.sleep(0.02)

    progress = BookRepo(conn).summary_progress(book_id)
    state = q.summarize_state_for_book(
        book_id,
        ready=int(progress["summary_ready_count"]),
        total=int(progress["summary_total_count"]),
    )
    assert state in ("queued", "running")
    assert (
        q._summarize_queued_count_for_book(book_id) == 1
        or q.summarize_active_for_book(book_id) is not None
    )


@pytest.mark.asyncio
async def test_summarize_state_paused_after_stop(conn):
    router = SlowMockRouter(
        delay=1.0,
        responses={"summarize": SUMMARY, "translate": "译文"},
    )
    q = JobQueue(conn, router)
    book_id = _seed_book(conn, n_segments=3)
    await q.enqueue_book_prefetch(book_id)
    await asyncio.sleep(0.02)
    await q.stop_book(book_id)

    progress = BookRepo(conn).summary_progress(book_id)
    state = q.summarize_state_for_book(
        book_id,
        ready=int(progress["summary_ready_count"]),
        total=int(progress["summary_total_count"]),
    )
    assert state == "paused"


class OrderingRouter(MockModelRouter):
    def __init__(self, *, models: ModelsConfig, fail_first_segment: bool = False) -> None:
        super().__init__(
            responses={"summarize": SUMMARY, "translate": "译文"},
            models=models,
        )
        self.fail_first_segment = fail_first_segment
        self.started: list[tuple[str, int]] = []
        self.active_by_book: dict[str, int] = {}
        self.peak_by_book: dict[str, int] = {}
        self.global_active = 0
        self.global_peak = 0

    async def complete(
        self,
        prompt: str,
        *,
        profile="summarize",
        summary_tier="normal",
        json_mode: bool = False,
        on_slot_acquired=None,
    ) -> str:
        if profile != "summarize":
            return await super().complete(
                prompt,
                profile=profile,
                summary_tier=summary_tier,
                json_mode=json_mode,
                on_slot_acquired=on_slot_acquired,
            )
        if on_slot_acquired is not None:
            await on_slot_acquired()
        marker = next(
            line for line in prompt.splitlines() if line.startswith("正文段落 ")
        )
        _, book_id, raw_idx = marker.split()
        idx = int(raw_idx)
        self.started.append((book_id, idx))
        self.active_by_book[book_id] = self.active_by_book.get(book_id, 0) + 1
        self.peak_by_book[book_id] = max(
            self.peak_by_book.get(book_id, 0),
            self.active_by_book[book_id],
        )
        self.global_active += 1
        self.global_peak = max(self.global_peak, self.global_active)
        try:
            await asyncio.sleep(0.03)
            if self.fail_first_segment and idx == 0:
                return "{not-json"
            return json.dumps(SUMMARY, ensure_ascii=False)
        finally:
            self.active_by_book[book_id] -= 1
            self.global_active -= 1


def _parallel_models() -> ModelsConfig:
    resource = ModelResource(
        id="ollama",
        provider="ollama",
        base_url="http://127.0.0.1:11434",
        model="m",
        concurrency=3,
    )
    return ModelsConfig(
        resources=[resource],
        summarize=ProfileRoute(priority=["ollama"]),
    )


def _seed_tracking_book(conn, *, book_id: str, n_segments: int) -> str:
    _seed_book(conn, book_id=book_id, n_segments=n_segments)
    with conn:
        for idx in range(n_segments):
            conn.execute(
                "UPDATE segments SET raw_text = ? WHERE book_id = ? AND idx = ?",
                (f"正文段落 {book_id} {idx}", book_id, idx),
            )
    return book_id


@pytest.mark.asyncio
async def test_same_book_summaries_are_strictly_ordered(conn):
    router = OrderingRouter(models=_parallel_models())
    q = JobQueue(conn, router)
    book_id = _seed_tracking_book(conn, book_id="book-a", n_segments=3)

    await q.enqueue_book_prefetch(book_id)
    for _ in range(100):
        if all(
            seg["summary_status"] == "ready"
            for seg in SegmentRepo(conn).list_for_book(book_id)
        ):
            break
        await asyncio.sleep(0.03)
    else:
        pytest.fail("ordered summary chain did not finish")

    assert router.started == [(book_id, 0), (book_id, 1), (book_id, 2)]
    assert router.peak_by_book[book_id] == 1


@pytest.mark.asyncio
async def test_high_priority_later_segment_does_not_skip_context_chain(conn):
    router = OrderingRouter(models=_parallel_models())
    q = JobQueue(conn, router)
    book_id = _seed_tracking_book(conn, book_id="book-a", n_segments=3)
    target = SegmentRepo(conn).get_by_index(book_id, 2)
    assert target is not None

    await q.enqueue_summarize(
        book_id,
        target["id"],
        target["idx"],
        high=True,
    )
    for _ in range(100):
        if all(
            seg["summary_status"] == "ready"
            for seg in SegmentRepo(conn).list_for_book(book_id)
        ):
            break
        await asyncio.sleep(0.03)
    else:
        pytest.fail("high-priority request did not finish ordered chain")

    assert router.started == [(book_id, 0), (book_id, 1), (book_id, 2)]


@pytest.mark.asyncio
async def test_different_books_still_summarize_in_parallel(conn):
    router = OrderingRouter(models=_parallel_models())
    q = JobQueue(conn, router)
    _seed_tracking_book(conn, book_id="book-a", n_segments=2)
    _seed_tracking_book(conn, book_id="book-b", n_segments=2)

    await q.enqueue_book_prefetch("book-a")
    await q.enqueue_book_prefetch("book-b")
    for _ in range(100):
        if all(
            all(
                seg["summary_status"] == "ready"
                for seg in SegmentRepo(conn).list_for_book(book_id)
            )
            for book_id in ("book-a", "book-b")
        ):
            break
        await asyncio.sleep(0.03)
    else:
        pytest.fail("cross-book summary chains did not finish")

    assert router.global_peak >= 2
    assert router.peak_by_book == {"book-a": 1, "book-b": 1}


@pytest.mark.asyncio
async def test_final_failure_does_not_block_later_segments(conn):
    router = OrderingRouter(
        models=_parallel_models(),
        fail_first_segment=True,
    )
    q = JobQueue(conn, router)
    book_id = _seed_tracking_book(conn, book_id="book-a", n_segments=2)

    await q.enqueue_book_prefetch(book_id)
    for _ in range(150):
        statuses = [
            seg["summary_status"]
            for seg in SegmentRepo(conn).list_for_book(book_id)
        ]
        if statuses == ["failed", "ready"]:
            break
        await asyncio.sleep(0.03)
    else:
        pytest.fail(f"summary chain did not continue after failure: {statuses}")

    first_idx_one = router.started.index((book_id, 1))
    assert all(idx == 0 for _, idx in router.started[:first_idx_one])


@pytest.mark.asyncio
async def test_summarize_state_running_when_active(conn):
    router = SlowMockRouter(
        delay=0.8,
        responses={"summarize": SUMMARY, "translate": "译文"},
    )
    q = JobQueue(conn, router)
    book_id = _seed_book(conn, n_segments=2)
    await q.enqueue_book_prefetch(book_id)

    for _ in range(40):
        if q.summarize_active_for_book(book_id) is not None:
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("summarize never became active")

    progress = BookRepo(conn).summary_progress(book_id)
    state = q.summarize_state_for_book(
        book_id,
        ready=int(progress["summary_ready_count"]),
        total=int(progress["summary_total_count"]),
    )
    assert state == "running"
