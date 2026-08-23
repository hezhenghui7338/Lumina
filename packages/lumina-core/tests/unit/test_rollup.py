"""Hierarchical summary packing and rollup tree tests."""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from lumina_core.db.repos import BookRepo, SegmentRepo, SummaryNodeRepo
from lumina_core.db.schema import init_db
from lumina_core.jobs.queue import JobQueue
from lumina_core.summarize.rollup import (
    PackItem,
    concat_chars,
    leaves_from_segments,
    next_windows,
    pack_by_chapter,
)
from tests.support.mock_router import MockModelRouter, load_json_fixture

SUMMARY = load_json_fixture(
    __import__("pathlib").Path(__file__).resolve().parents[1] / "fixtures" / "llm" / "summary_segment0.json"
)


def _item(text: str, idx: int, *, chapter: str | None = None) -> PackItem:
    return PackItem(text=text, idx_start=idx, idx_end=idx, chapter=chapter, label=f"段{idx + 1}")


def test_pack_by_chapter_splits_over_budget_within_chapter():
    items = [
        _item("甲" * 40, 0, chapter="一"),
        _item("乙" * 40, 1, chapter="一"),
        _item("丙" * 40, 2, chapter="一"),
    ]
    windows = pack_by_chapter(items, max_chars=90)
    assert len(windows) == 2
    assert [i.idx_start for i in windows[0]] == [0, 1]
    assert [i.idx_start for i in windows[1]] == [2]


def test_pack_by_chapter_keeps_chapter_boundaries():
    items = [
        _item("甲" * 20, 0, chapter="一"),
        _item("乙" * 20, 1, chapter="二"),
    ]
    windows = pack_by_chapter(items, max_chars=1000)
    assert len(windows) == 2
    assert windows[0][0].chapter == "一"
    assert windows[1][0].chapter == "二"


def test_next_windows_short_book_synthesizes_root_only():
    items = [_item("短摘要", 0), _item("也短", 1)]
    assert concat_chars(items) < 100
    assert next_windows(items, max_chars=100) is None


def test_next_windows_multi_layer():
    items = [_item("X" * 30, i, chapter="一") for i in range(6)]
    windows = next_windows(items, max_chars=70)
    assert windows is not None
    assert len(windows) >= 2
    # Each window still over one item → another layer would be needed if concat of
    # synthesized parents exceeds budget; packing itself is deterministic.
    assert all(len(w) >= 1 for w in windows)


def test_leaves_from_segments_skip_empty():
    rows = [
        {
            "id": "s1",
            "idx": 0,
            "label": "开篇",
            "chapter": "一",
            "summary_json": json.dumps(
                {"sentences": ["主角上路。"], "bullets": [{"label": "启程", "body": "辞别乡邻。"}]}
            ),
        },
        {"id": "s2", "idx": 1, "label": "空", "chapter": "一", "summary_json": "{}"},
    ]
    leaves = leaves_from_segments(rows)
    assert len(leaves) == 1
    assert leaves[0].idx_start == 0
    assert "主角上路" in leaves[0].text


@pytest.mark.asyncio
async def test_enqueue_rollup_after_all_ready(tmp_path):
    conn = init_db(tmp_path / "r.db")
    book_id = "book-r"
    BookRepo(conn).insert(
        id=book_id,
        title="T",
        format="txt",
        file_path="/tmp/t.txt",
        segment_count=2,
        status="reading",
    )
    segs = [
        {
            "id": str(uuid.uuid4()),
            "book_id": book_id,
            "idx": i,
            "anchor_label": f"段 {i + 1}",
            "raw_text": f"正文 {i} " + "字" * 40,
            "summary_status": "pending",
            "retry_count": 0,
        }
        for i in range(2)
    ]
    SegmentRepo(conn).insert_many(segs)
    repo = SegmentRepo(conn)
    for seg in segs:
        repo.update_summary(
            seg["id"],
            summary_json=json.dumps(SUMMARY, ensure_ascii=False),
            label="标签",
            status="ready",
        )
    BookRepo(conn).maybe_mark_summarized(book_id)
    router = MockModelRouter(responses={"summarize": SUMMARY})
    q = JobQueue(conn, router)
    await q.enqueue_rollup(book_id)

    for _ in range(40):
        book = BookRepo(conn).get(book_id)
        if book and book.get("index_status") == "ready":
            break
        await asyncio.sleep(0.1)
    else:
        pytest.fail(f"index not ready: {BookRepo(conn).get(book_id)}")

    root = SummaryNodeRepo(conn).get_root(book_id)
    assert root is not None
    assert root["level"] == 0
    nodes = SummaryNodeRepo(conn).list_for_book(book_id)
    assert any(n.get("segment_id") for n in nodes)


@pytest.mark.asyncio
async def test_regenerate_clears_index(tmp_path):
    conn = init_db(tmp_path / "r2.db")
    book_id = "book-r2"
    BookRepo(conn).insert(
        id=book_id,
        title="T",
        format="txt",
        file_path="/tmp/t.txt",
        segment_count=1,
        status="summarized",
    )
    seg_id = str(uuid.uuid4())
    SegmentRepo(conn).insert_many(
        [
            {
                "id": seg_id,
                "book_id": book_id,
                "idx": 0,
                "anchor_label": "段 1",
                "raw_text": "正文",
                "summary_status": "ready",
                "retry_count": 0,
            }
        ]
    )
    SegmentRepo(conn).update_summary(
        seg_id,
        summary_json=json.dumps(SUMMARY, ensure_ascii=False),
        label="标签",
        status="ready",
    )
    SummaryNodeRepo(conn).replace_for_book(
        book_id,
        [
            {
                "id": "n1",
                "level": 0,
                "parent_id": None,
                "sort_idx": 0,
                "segment_id": None,
                "segment_idx_start": 0,
                "segment_idx_end": 0,
                "chapter": None,
                "label": "全书",
                "summary_json": "{}",
                "status": "ready",
            }
        ],
    )
    BookRepo(conn).update(book_id, index_status="ready")
    router = MockModelRouter(responses={"summarize": SUMMARY})
    q = JobQueue(conn, router)
    await q.enqueue_book_regenerate(book_id)
    book = BookRepo(conn).get(book_id)
    assert book["index_status"] == "idle"
    assert SummaryNodeRepo(conn).get_root(book_id) is None
