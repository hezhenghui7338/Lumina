"""In-book original-text search (PRD B13)."""

from __future__ import annotations

import inspect

import pytest
from fastapi.testclient import TestClient

from lumina_core.api import routes
from lumina_core.config import Settings
from lumina_core.db.repos import SegmentRepo
from lumina_core.db.schema import init_db
from lumina_core.main import create_app
from lumina_core.search.original import make_snippet, search_original, utf16_offset


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app) as c:
        yield c


def _seed_book(conn, book_id: str = "b1") -> None:
    conn.execute(
        """
        INSERT INTO books (id, title, format, file_path, created_at, updated_at)
        VALUES (?, '原文检索', 'txt', '/x', 'now', 'now')
        """,
        (book_id,),
    )
    conn.commit()


def test_utf16_offset_emoji_and_cjk():
    text = "学而😊时习"
    assert utf16_offset(text, 0) == 0
    assert utf16_offset(text, 2) == 2
    # emoji is one Python char, two UTF-16 code units
    assert utf16_offset(text, 3) == 4
    assert utf16_offset(text, len(text)) == len(text.encode("utf-16-le")) // 2


def test_utf16_offset_does_not_require_codec_missing_from_release_sidecar():
    source = inspect.getsource(utf16_offset)
    assert ".encode(" not in source
    assert utf16_offset("甲😊乙", 99) == 4


def test_snippet_marks_match_and_strips_newlines():
    text = "子曰：\n学而时习之"
    start = text.index("学而")
    end = start + 2
    snippet = make_snippet(text, start, end)
    assert "[学而]" in snippet
    assert "\n" not in snippet


def test_search_original_hits_raw_text_only(tmp_path):
    conn = init_db(tmp_path / "t.db")
    _seed_book(conn)
    SegmentRepo(conn).insert_many(
        [
            {
                "id": "s0",
                "book_id": "b1",
                "idx": 0,
                "raw_text": "邻里虽敬其向学，却无力资助书卷。",
                "summary_status": "ready",
            },
            {
                "id": "s1",
                "book_id": "b1",
                "idx": 1,
                "raw_text": "主角离乡赴考。",
                "summary_status": "ready",
            },
        ]
    )
    SegmentRepo(conn).update_summary(
        "s1",
        summary_json='{"sentences":["邻里虽敬其向学"],"bullets":[],"label":"邻里"}',
        label="邻里虽敬",
        status="ready",
    )
    conn.execute("UPDATE segments SET translation = ? WHERE id = ?", ("邻里虽敬其向学", "s1"))
    conn.commit()

    hits = search_original(conn, "b1", "邻里虽敬")["hits"]
    assert len(hits) == 1
    assert hits[0]["segment_index"] == 0
    assert "raw_text" not in hits[0]
    assert "[邻里虽敬]" in hits[0]["snippet"]
    start = hits[0]["start"]
    raw = "邻里虽敬其向学，却无力资助书卷。"
    assert raw[start : hits[0]["end"]] == "邻里虽敬"


def test_search_original_case_insensitive_ascii(tmp_path):
    conn = init_db(tmp_path / "t.db")
    _seed_book(conn)
    SegmentRepo(conn).insert_many(
        [
            {
                "id": "s0",
                "book_id": "b1",
                "idx": 0,
                "raw_text": "Hello World from the village.",
                "summary_status": "pending",
            }
        ]
    )
    hits = search_original(conn, "b1", "hello")["hits"]
    assert len(hits) == 1
    assert hits[0]["start"] == 0
    assert hits[0]["end"] == 5


def test_search_original_multiple_hits_and_limit(tmp_path):
    conn = init_db(tmp_path / "t.db")
    _seed_book(conn)
    SegmentRepo(conn).insert_many(
        [
            {
                "id": "s0",
                "book_id": "b1",
                "idx": 0,
                "raw_text": "甲甲甲",
                "summary_status": "pending",
            },
            {
                "id": "s1",
                "book_id": "b1",
                "idx": 1,
                "raw_text": "甲乙",
                "summary_status": "pending",
            },
        ]
    )
    result = search_original(conn, "b1", "甲", limit=2)
    assert len(result["hits"]) == 2
    assert result["truncated"] is True
    assert result["hits"][0]["segment_index"] == 0
    assert result["hits"][1]["segment_index"] == 0
    assert result["hits"][1]["start"] == 1


def test_search_original_empty_query(tmp_path):
    conn = init_db(tmp_path / "t.db")
    _seed_book(conn)
    assert search_original(conn, "b1", "   ")["hits"] == []


def test_search_original_does_not_cross_books(tmp_path):
    conn = init_db(tmp_path / "t.db")
    _seed_book(conn, "b1")
    _seed_book(conn, "b2")
    SegmentRepo(conn).insert_many(
        [
            {
                "id": "s1",
                "book_id": "b1",
                "idx": 0,
                "raw_text": "独有此句",
                "summary_status": "pending",
            },
            {
                "id": "s2",
                "book_id": "b2",
                "idx": 0,
                "raw_text": "独有此句 也在乙书",
                "summary_status": "pending",
            },
        ]
    )
    hits = search_original(conn, "b1", "独有此句")["hits"]
    assert len(hits) == 1
    assert hits[0]["segment_index"] == 0


def test_original_search_api_never_returns_raw_text(client):
    conn = client.app.state.lumina.conn  # type: ignore[attr-defined]
    conn.execute(
        "INSERT INTO books (id, title, format, file_path, created_at, updated_at) "
        "VALUES ('ob', 't', 'txt', '/x', 'now', 'now')"
    )
    SegmentRepo(conn).insert_many(
        [
            {
                "id": "os",
                "book_id": "ob",
                "idx": 0,
                "raw_text": "SECRET_RAW " + ("甲" * 80) + "学而时习之",
                "summary_status": "pending",
            }
        ]
    )
    missing = client.get("/books/nope/original-search", params={"q": "学而"})
    assert missing.status_code == 404

    empty = client.get("/books/ob/original-search", params={"q": "   "})
    assert empty.status_code == 200
    assert empty.json()["hits"] == []

    resp = client.get("/books/ob/original-search", params={"q": "学而"})
    assert resp.status_code == 200
    body = resp.json()
    assert "raw_text" not in body
    assert body["hits"]
    hit = body["hits"][0]
    assert "raw_text" not in hit
    assert hit["segment_index"] == 0
    assert "[学而]" in hit["snippet"]
    assert "SECRET_RAW" not in resp.text


def test_original_search_handler_uses_to_thread():
    source = inspect.getsource(routes.search_book_original)
    assert "asyncio.to_thread" in source
    assert "search_original" in source
