"""Summary segment timeout and stale running recovery."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from lumina_core.db.repos import BookRepo, SegmentRepo
from lumina_core.db.schema import init_db
from lumina_core.jobs.queue import JobQueue
from tests.support.mock_router import MockModelRouter, load_json_fixture

LLM_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "llm"
SUMMARY = load_json_fixture(LLM_FIXTURES / "summary_segment0.json")


class HangingMockRouter(MockModelRouter):
    async def complete(self, prompt: str, *, profile="summarize", json_mode: bool = False) -> str:
        await asyncio.sleep(3600)
        return await super().complete(prompt, profile=profile, json_mode=json_mode)


def _seed_book(conn, *, book_id: str = "book-timeout", n_segments: int = 1) -> str:
    BookRepo(conn).insert(
        id=book_id,
        title="Timeout Test",
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
    return init_db(tmp_path / "timeout.db")


@pytest.mark.asyncio
async def test_summarize_timeout_marks_error_then_retries(conn):
    router = HangingMockRouter(responses={"summarize": SUMMARY, "translate": "译文"})
    q = JobQueue(conn, router)
    book_id = _seed_book(conn)
    segs = SegmentRepo(conn).list_for_book(book_id)
    seg = segs[0]

    with patch(
        "lumina_core.config.SUMMARY_SEGMENT_TIMEOUT_SECONDS",
        0.15,
    ):
        await q.enqueue_summarize(book_id, seg["id"], seg["idx"], high=True)
        for _ in range(40):
            updated = SegmentRepo(conn).get_by_index(book_id, 0)
            status = updated["summary_status"]
            if status in ("error", "failed"):
                break
            await asyncio.sleep(0.05)
        else:
            pytest.fail("segment never left running after timeout")

    updated = SegmentRepo(conn).get_by_index(book_id, 0)
    assert updated["summary_status"] in ("error", "failed")
    assert updated["retry_count"] >= 1


@pytest.mark.asyncio
async def test_recover_stale_running_resets_orphan_segments(conn):
    router = MockModelRouter(responses={"summarize": SUMMARY, "translate": "译文"})
    q = JobQueue(conn, router)
    book_id = _seed_book(conn)
    segs = SegmentRepo(conn).list_for_book(book_id)
    seg = segs[0]
    SegmentRepo(conn).set_status(seg["id"], "running")

    await q._recover_stale_running(book_id)

    updated = SegmentRepo(conn).get_by_index(book_id, 0)
    assert updated["summary_status"] == "pending"
    assert q._active == {}


@pytest.mark.asyncio
async def test_recover_stale_running_skips_active_jobs(conn):
    router = MockModelRouter(responses={"summarize": SUMMARY, "translate": "译文"})
    q = JobQueue(conn, router)
    book_id = _seed_book(conn)
    segs = SegmentRepo(conn).list_for_book(book_id)
    seg = segs[0]
    SegmentRepo(conn).set_status(seg["id"], "running")

    from lumina_core.jobs.queue import JobItem, JobKind

    key = f"{book_id}:{seg['id']}:{JobKind.SUMMARIZE.value}"
    q._active[key] = JobItem(
        priority=0,
        book_id=book_id,
        segment_id=seg["id"],
        segment_idx=0,
        kind=JobKind.SUMMARIZE,
    )

    await q._recover_stale_running(book_id)

    updated = SegmentRepo(conn).get_by_index(book_id, 0)
    assert updated["summary_status"] == "running"


@pytest.mark.asyncio
async def test_enqueue_book_prefetch_recovers_stale_running(conn):
    router = MockModelRouter(responses={"summarize": SUMMARY, "translate": "译文"})
    q = JobQueue(conn, router)
    book_id = _seed_book(conn)
    segs = SegmentRepo(conn).list_for_book(book_id)
    seg = segs[0]
    SegmentRepo(conn).set_status(seg["id"], "running")

    await q.enqueue_book_prefetch(book_id)

    for _ in range(50):
        updated = SegmentRepo(conn).get_by_index(book_id, 0)
        if updated["summary_status"] == "ready":
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("stale running segment was not summarized after prefetch")

    updated = SegmentRepo(conn).get_by_index(book_id, 0)
    assert updated["summary_status"] == "ready"


@pytest.mark.asyncio
async def test_recover_on_startup_resumes_incomplete_books(conn):
    router = MockModelRouter(responses={"summarize": SUMMARY, "translate": "译文"})
    q = JobQueue(conn, router)
    book_id = _seed_book(conn)
    segs = SegmentRepo(conn).list_for_book(book_id)
    SegmentRepo(conn).set_status(segs[0]["id"], "running")

    await q.recover_on_startup()

    for _ in range(50):
        updated = SegmentRepo(conn).get_by_index(book_id, 0)
        if updated["summary_status"] == "ready":
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("startup recovery did not complete summarize for orphan running segment")

    assert SegmentRepo(conn).get_by_index(book_id, 0)["summary_status"] == "ready"
