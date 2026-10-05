"""Original-text index for in-book search (PRD B13 hit list)."""

from __future__ import annotations

import time

import pytest

from lumina_core.db.repos import SegmentRepo
from lumina_core.db.schema import init_db
from lumina_core.search.original import search_original
from lumina_core.search.original_index import (
    backfill_original_indexes,
    index_book_original,
    is_original_index_ready,
)


def _seed_book(conn, book_id: str = "b1", *, segment_count: int = 1) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO books (id, title, format, file_path, segment_count, status, created_at, updated_at)
        VALUES (?, '原文检索', 'txt', '/x', ?, 'unread', 'now', 'now')
        """,
        (book_id, segment_count),
    )
    conn.commit()


def test_index_ready_after_index_book(tmp_path):
    conn = init_db(tmp_path / "t.db")
    _seed_book(conn, segment_count=2)
    SegmentRepo(conn).insert_many(
        [
            {
                "id": "s0",
                "book_id": "b1",
                "idx": 0,
                "raw_text": "学而时习之",
                "summary_status": "pending",
                "label": "开篇",
            },
            {
                "id": "s1",
                "book_id": "b1",
                "idx": 1,
                "raw_text": "不亦说乎",
                "summary_status": "pending",
            },
        ]
    )
    assert is_original_index_ready(conn, "b1") is False
    index_book_original(conn, "b1", replace=True)
    assert is_original_index_ready(conn, "b1") is True

    result = search_original(conn, "b1", "学而")
    assert result["index_ready"] is True
    assert len(result["hits"]) == 1
    assert result["hits"][0]["segment_index"] == 0
    assert result["hits"][0].get("segment_label") == "开篇"
    assert "[学而]" in result["hits"][0]["snippet"]


def test_short_query_uses_char_index(tmp_path):
    conn = init_db(tmp_path / "t.db")
    _seed_book(conn, segment_count=2)
    SegmentRepo(conn).insert_many(
        [
            {
                "id": "s0",
                "book_id": "b1",
                "idx": 0,
                "raw_text": "甲乙丙",
                "summary_status": "pending",
            },
            {
                "id": "s1",
                "book_id": "b1",
                "idx": 1,
                "raw_text": "丁戊己",
                "summary_status": "pending",
            },
        ]
    )
    index_book_original(conn, "b1", replace=True)
    one = search_original(conn, "b1", "甲")
    assert one["index_ready"] is True
    assert len(one["hits"]) == 1
    two = search_original(conn, "b1", "乙丙")
    assert len(two["hits"]) == 1
    assert two["hits"][0]["start"] == 1


def test_long_query_uses_fts(tmp_path):
    conn = init_db(tmp_path / "t.db")
    _seed_book(conn, segment_count=1)
    SegmentRepo(conn).insert_many(
        [
            {
                "id": "s0",
                "book_id": "b1",
                "idx": 0,
                "raw_text": "邻里虽敬其向学，却无力资助书卷。",
                "summary_status": "pending",
            }
        ]
    )
    index_book_original(conn, "b1", replace=True)
    result = search_original(conn, "b1", "邻里虽敬")
    assert result["index_ready"] is True
    assert len(result["hits"]) == 1


def test_unindexed_falls_back_with_flag(tmp_path):
    conn = init_db(tmp_path / "t.db")
    _seed_book(conn, segment_count=1)
    SegmentRepo(conn).insert_many(
        [
            {
                "id": "s0",
                "book_id": "b1",
                "idx": 0,
                "raw_text": "学而时习之",
                "summary_status": "pending",
            }
        ]
    )
    result = search_original(conn, "b1", "学而")
    assert result["index_ready"] is False
    assert len(result["hits"]) == 1


def test_backfill_indexes_missing_books(tmp_path):
    conn = init_db(tmp_path / "t.db")
    _seed_book(conn, segment_count=1)
    SegmentRepo(conn).insert_many(
        [
            {
                "id": "s0",
                "book_id": "b1",
                "idx": 0,
                "raw_text": "学而时习之",
                "summary_status": "pending",
            }
        ]
    )
    assert backfill_original_indexes(conn, max_books=1) == 1
    assert is_original_index_ready(conn, "b1") is True
    assert backfill_original_indexes(conn, max_books=1) == 0


@pytest.mark.perf
def test_indexed_search_first_page_under_100ms_on_large_book(tmp_path):
    """Synthetic ~10k segments / ~20M chars; indexed first page must stay snappy."""
    conn = init_db(tmp_path / "perf.db")
    n_segs = 10_000
    # ~2000 chars/seg ≈ 20M total.
    filler = ("正文内容重复填充。" * 250)[:2000]
    assert len(filler) == 2000
    _seed_book(conn, segment_count=n_segs)
    rows = []
    for i in range(n_segs):
        text = filler
        if i == 10:
            text = "前缀" + "稀有关键词XYZ" + filler[10:]
        rows.append(
            {
                "id": f"s{i}",
                "book_id": "b1",
                "idx": i,
                "raw_text": text,
                "summary_status": "pending",
            }
        )
        if len(rows) >= 200:
            SegmentRepo(conn).insert_many(rows)
            rows = []
    if rows:
        SegmentRepo(conn).insert_many(rows)

    index_book_original(conn, "b1", replace=True)
    assert is_original_index_ready(conn, "b1")

    # Warm once (FTS / page cache), then measure.
    search_original(conn, "b1", "稀有关键词XYZ", limit=30)
    t0 = time.perf_counter()
    result = search_original(conn, "b1", "稀有关键词XYZ", limit=30)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert result["index_ready"] is True
    assert result["hits"]
    assert result["hits"][0]["segment_index"] == 10
    assert elapsed_ms < 100.0, f"indexed search took {elapsed_ms:.1f}ms"
    conn.close()
