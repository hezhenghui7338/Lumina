"""Regression: never-freeze invariants (slim list API, WAL, event loop)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumina_core.config import Settings
from lumina_core.db.repos import SegmentRepo
from lumina_core.db.schema import init_db
from lumina_core.main import create_app
from lumina_core.models.router import set_router
from tests.support.import_helpers import import_sample_book
from tests.support.mock_router import MockModelRouter, load_json_fixture

LLM_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "llm"
BOOK_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "books"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMINA_DATA_DIR", str(tmp_path))
    router = MockModelRouter(
        responses={
            "summarize": load_json_fixture(LLM_FIXTURES / "summary_segment0.json"),
            "chat": load_json_fixture(LLM_FIXTURES / "chat_with_citation.json"),
            "translate": "示例译文。",
        }
    )
    app = create_app(Settings(data_dir=tmp_path))
    app.state.lumina.router = router
    app.state.lumina.job_queue.router = router
    set_router(router)
    with TestClient(app) as c:
        yield c


def test_sqlite_wal_enabled(tmp_path):
    conn = init_db(tmp_path / "t.db")
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert str(mode).lower() == "wal"
    conn.close()


def test_list_segments_excludes_raw_text_and_summary_json(client):
    book_id = import_sample_book(client)
    segs = client.get(f"/books/{book_id}/segments").json()["segments"]
    assert segs
    assert "raw_text" not in segs[0]
    assert "translation" not in segs[0]
    assert "summary_json" not in segs[0]

    detail = client.get(f"/books/{book_id}/segments/0").json()
    assert detail.get("raw_text")


def test_get_segment_summary(tmp_path, client):
    conn = init_db(tmp_path / "t3.db")
    conn.execute(
        "INSERT INTO books (id, title, format, file_path, created_at, updated_at) "
        "VALUES ('b3', 't', 'txt', '/x', 'now', 'now')"
    )
    SegmentRepo(conn).insert_many(
        [
            {
                "id": "s3",
                "book_id": "b3",
                "idx": 0,
                "chapter": None,
                "page_range": None,
                "anchor_label": "a",
                "raw_text": "hello",
                "summary_status": "ready",
                "retry_count": 0,
            }
        ]
    )
    repo = SegmentRepo(conn)
    repo.update_summary(
        "s3",
        summary_json='{"sentences":["x"],"bullets":[],"label":"a","anchor":"b"}',
        label="a",
        status="ready",
    )
    summary = repo.get_summary_by_index("b3", 0)
    assert summary is not None
    assert summary["summary_json"]
    assert "raw_text" not in summary
    conn.close()

    book_id = import_sample_book(client)
    import time

    for _ in range(50):
        api_summary = client.get(f"/books/{book_id}/segments/0/summary").json()
        if api_summary.get("summary_json"):
            break
        time.sleep(0.05)
    assert api_summary.get("summary_json")
    assert "raw_text" not in api_summary
    assert api_summary["idx"] == 0


def test_list_segments_include_summary_query(client):
    book_id = import_sample_book(client)
    segs = client.get(
        f"/books/{book_id}/segments", params={"include_summary": "true"}
    ).json()["segments"]
    assert segs
    assert "summary_json" in segs[0]


def test_list_for_book_include_body_flag(tmp_path):
    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO books (id, title, format, file_path, created_at, updated_at) "
        "VALUES ('b1', 't', 'txt', '/x', 'now', 'now')"
    )
    SegmentRepo(conn).insert_many(
        [
            {
                "id": "s1",
                "book_id": "b1",
                "idx": 0,
                "chapter": None,
                "page_range": None,
                "anchor_label": "a",
                "raw_text": "hello world " * 100,
                "summary_status": "pending",
                "retry_count": 0,
            }
        ]
    )
    meta = SegmentRepo(conn).list_for_book("b1", include_body=False)
    full = SegmentRepo(conn).list_for_book("b1", include_body=True)
    assert "raw_text" not in meta[0]
    assert "translation" not in meta[0]
    assert "summary_json" not in meta[0]
    assert "summary_provider" in meta[0]
    assert "summary_model" in meta[0]
    assert full[0]["raw_text"].startswith("hello")
    conn.close()


def test_list_for_book_backfills_char_count(tmp_path):
    conn = init_db(tmp_path / "t2.db")
    conn.execute(
        "INSERT INTO books (id, title, format, file_path, created_at, updated_at) "
        "VALUES ('b2', 't', 'txt', '/x', 'now', 'now')"
    )
    SegmentRepo(conn).insert_many(
        [
            {
                "id": "s2",
                "book_id": "b2",
                "idx": 0,
                "chapter": None,
                "page_range": None,
                "anchor_label": "a",
                "raw_text": "abcd",
                "summary_status": "pending",
                "retry_count": 0,
            }
        ]
    )
    conn.execute("UPDATE segments SET char_count = NULL WHERE id = 's2'")
    conn.commit()
    repo = SegmentRepo(conn)
    meta = repo.list_for_book("b2", include_body=False)
    assert meta[0]["char_count"] is None
    repo.backfill_char_counts("b2")
    meta = repo.list_for_book("b2", include_body=False)
    assert meta[0]["char_count"] == 4
    conn.close()


def test_health_during_import(client):
    sample = BOOK_FIXTURES / "sample.txt"
    # Import is synchronous from TestClient POV, but /health must still be wired.
    assert client.get("/health").json()["status"] == "ok"
    resp = client.post("/books/import", json={"paths": [str(sample)]})
    assert resp.status_code == 200
    assert client.get("/health").json()["status"] == "ok"


def test_health_responds_during_news_read(client, monkeypatch, tmp_path):
    """News read must not block the sidecar event loop (/health stays responsive)."""
    from lumina_core.news.fetch import FetchResult
    from lumina_core.news.store import NewsArticle, NewsSourceRepo, NewsStore

    conn = client.app.state.lumina.conn  # type: ignore[attr-defined]
    source = NewsSourceRepo(conn).add_source("https://example.com/feed", "Example")
    NewsStore(conn).upsert(
        NewsArticle(
            id="art-health",
            source_id=source["id"],
            url="https://example.com/health",
            title="Health During Read",
            excerpt="Testing health during read.",
        )
    )

    def slow_fetch(url: str, **kwargs):
        return FetchResult(
            url=url,
            title="Health During Read",
            text=("段落。" * 200),
            strategy="direct",
        )

    monkeypatch.setattr("lumina_core.news.read.fetch_article", slow_fetch)

    assert client.get("/health").json()["status"] == "ok"
    read = client.post("/news/articles/art-health/read", json={})
    assert read.status_code == 200
    assert client.get("/health").json()["status"] == "ok"


def test_health_responds_during_get_segment(client, monkeypatch):
    """Segment detail read must not block the sidecar event loop."""
    import threading
    import time

    book_id = import_sample_book(client)
    orig_get = SegmentRepo.get_by_index

    def slow_get_by_index(self, book_id, idx):
        time.sleep(0.2)
        return orig_get(self, book_id, idx)

    monkeypatch.setattr(SegmentRepo, "get_by_index", slow_get_by_index)

    health_during: list[str] = []

    def fetch_segment():
        client.get(f"/books/{book_id}/segments/0")

    worker = threading.Thread(target=fetch_segment)
    worker.start()
    time.sleep(0.05)
    health_during.append(client.get("/health").json()["status"])
    worker.join(timeout=5)
    assert worker.is_alive() is False
    assert health_during == ["ok"]
