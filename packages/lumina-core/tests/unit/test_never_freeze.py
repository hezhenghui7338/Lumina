"""Regression: never-freeze invariants (slim list API, WAL, event loop)."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumina_core.config import Settings
from lumina_core.db.connection import db_lock
from lumina_core.db.repos import BookRepo, SegmentRepo
from lumina_core.db.schema import init_db
from lumina_core.jobs.ingest import _persist_ingest_sync
from lumina_core.jobs.resegment import _persist_resegment_sync
from lumina_core.main import create_app
from lumina_core.models.router import set_router
from tests.support.import_helpers import import_sample_book, wait_for_ingest
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


def test_ingest_persist_does_not_wait_for_api_connection_lock(tmp_path):
    """Import writes use another WAL connection, not the API connection lock."""
    db_path = tmp_path / "concurrent.db"
    api_conn = init_db(db_path)
    BookRepo(api_conn).insert(
        id="importing",
        title="Importing",
        format="txt",
        file_path="/tmp/importing.txt",
        segment_count=0,
        status="processing",
    )
    segments = [
        {
            "id": "import-segment",
            "book_id": "importing",
            "idx": 0,
            "raw_text": "正文",
            "summary_status": "pending",
        }
    ]
    errors: list[BaseException] = []

    def persist() -> None:
        try:
            _persist_ingest_sync(
                db_path,
                book_id="importing",
                src=Path("/tmp/importing.txt"),
                metadata={},
                detected_language="zh",
                target_language="zh-CN",
                segments=segments,
                ingest_meta={"total_char_count": 2},
            )
        except BaseException as exc:  # pragma: no cover - surfaced by assertion
            errors.append(exc)

    worker = threading.Thread(target=persist)
    with db_lock(api_conn):
        worker.start()
        worker.join(timeout=2)

    assert worker.is_alive() is False
    assert errors == []
    assert SegmentRepo(api_conn).get_by_index("importing", 0)["raw_text"] == "正文"
    api_conn.close()


def test_resegment_persist_does_not_wait_for_api_connection_lock(tmp_path):
    """Resegment replacement uses another WAL connection, not the API lock."""
    db_path = tmp_path / "resegment-concurrent.db"
    api_conn = init_db(db_path)
    BookRepo(api_conn).insert(
        id="resegmenting",
        title="Resegmenting",
        format="txt",
        file_path="/tmp/resegmenting.txt",
        segment_count=0,
        status="processing",
    )
    segments = [
        {
            "id": "new-segment",
            "book_id": "resegmenting",
            "idx": 0,
            "raw_text": "新正文",
            "summary_status": "pending",
        }
    ]
    errors: list[BaseException] = []

    def persist() -> None:
        try:
            _persist_resegment_sync(
                db_path,
                "resegmenting",
                segments,
                metadata_json={"chunk_target_chars": 2000},
                status="reading",
            )
        except BaseException as exc:  # pragma: no cover - surfaced by assertion
            errors.append(exc)

    worker = threading.Thread(target=persist)
    with db_lock(api_conn):
        worker.start()
        worker.join(timeout=2)

    assert worker.is_alive() is False
    assert errors == []
    assert SegmentRepo(api_conn).get_by_index("resegmenting", 0)["raw_text"] == "新正文"
    api_conn.close()


def test_txt_resegment_skips_commit_when_cancelled_after_stream(tmp_path, monkeypatch):
    """TXT resegment must not replace segments if cancel arrives after the last window."""
    from lumina_core.ingest.progress import DocumentLoadCancelled
    from lumina_core.ingest.txt_persist import persist_streamed_txt_resegment

    dest = tmp_path / "keep.txt"
    dest.write_text("第一章 开篇\n\n这是一段用于重新分段的正文。\n" * 30, encoding="utf-8")
    db_path = tmp_path / "resegment-cancel.db"
    conn = init_db(db_path)
    BookRepo(conn).insert(
        id="keep-me",
        title="Keep",
        format="txt",
        file_path=str(dest),
        segment_count=1,
        status="reading",
    )
    SegmentRepo(conn).insert_many(
        [
            {
                "id": "old-seg",
                "book_id": "keep-me",
                "idx": 0,
                "chapter": None,
                "page_range": None,
                "anchor_label": "a",
                "raw_text": "旧段",
                "summary_status": "pending",
                "retry_count": 0,
            }
        ]
    )
    conn.commit()
    conn.close()

    cancel = threading.Event()
    from lumina_core.chunker.stream import iter_txt_chunks as orig_iter

    def wrapping_iter(*args, **kwargs):
        yield from orig_iter(*args, **kwargs)
        cancel.set()

    monkeypatch.setattr("lumina_core.ingest.txt_persist.iter_txt_chunks", wrapping_iter)
    with pytest.raises(DocumentLoadCancelled):
        persist_streamed_txt_resegment(
            db_path,
            book_id="keep-me",
            dest=dest,
            chunk_target_chars=1500,
            old_metadata={},
            final_status="reading",
            segment_tier="normal",
            cancel_event=cancel,
        )
    check = init_db(db_path)
    segs = SegmentRepo(check).list_for_book("keep-me", include_body=False)
    assert [seg["id"] for seg in segs] == ["old-seg"]
    check.close()


def test_list_segments_excludes_raw_text_and_summary_json(client):
    book_id = import_sample_book(client)
    segs = client.get(f"/books/{book_id}/segments").json()["segments"]
    assert segs
    assert "raw_text" not in segs[0]
    assert "translation" not in segs[0]
    assert "summary_json" not in segs[0]

    detail = client.get(f"/books/{book_id}/segments/0").json()
    assert detail.get("raw_text")


def test_list_segments_includes_preview_without_summary_json(client):
    conn = client.app.state.lumina.conn  # type: ignore[attr-defined]
    conn.execute(
        "INSERT INTO books (id, title, format, file_path, created_at, updated_at) "
        "VALUES ('bp', 't', 'txt', '/x', 'now', 'now')"
    )
    SegmentRepo(conn).insert_many(
        [
            {
                "id": "sp",
                "book_id": "bp",
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
    sentence = "邻里虽敬其向学，却无力资助书卷。"
    SegmentRepo(conn).update_summary(
        "sp",
        summary_json=(
            '{"sentences":["'
            + sentence
            + '"],"bullets":[{"label":"邻里","body":"乡邻敬其向学。"}],'
            '"label":"邻里期望","anchor":"a"}'
        ),
        label="邻里期望",
        status="ready",
    )
    catalog = SegmentRepo(conn).list_catalog("bp")
    assert "summary_json" not in catalog[0]
    assert catalog[0]["summary_preview"] == sentence
    assert catalog[0]["bullet_labels"] == ["邻里"]

    segs = client.get("/books/bp/segments").json()["segments"]
    assert segs
    assert "summary_json" not in segs[0]
    assert "raw_text" not in segs[0]
    assert segs[0]["summary_preview"] == sentence
    assert segs[0]["label"] == "邻里期望"
    assert segs[0]["bullet_labels"] == ["邻里"]

    # Detail must decode bullet_labels to a JSON array (Swift SegmentRow), not DB TEXT.
    with conn:
        conn.execute(
            "UPDATE segments SET bullet_labels = ? WHERE id = ?",
            ('["邻里"]', "sp"),
        )
    detail = client.get("/books/bp/segments/0").json()
    assert detail["bullet_labels"] == ["邻里"]
    assert not isinstance(detail["bullet_labels"], str)

def test_list_catalog_heading_path_and_legacy_chapter_fallback(tmp_path):
    conn = init_db(tmp_path / "heading-path.db")
    conn.execute(
        "INSERT INTO books (id, title, format, file_path, created_at, updated_at) "
        "VALUES ('hp', 't', 'txt', '/x', 'now', 'now')"
    )
    SegmentRepo(conn).insert_many(
        [
            {
                "id": "hp0",
                "book_id": "hp",
                "idx": 0,
                "chapter": "§第一部分 · 第一章",
                "heading_path": ["第一部分", "第一章"],
                "page_range": None,
                "anchor_label": "a",
                "raw_text": "第一章正文",
                "summary_status": "pending",
                "retry_count": 0,
            },
            {
                "id": "hp1",
                "book_id": "hp",
                "idx": 1,
                "chapter": "§序言",
                "page_range": None,
                "anchor_label": "b",
                "raw_text": "序言正文",
                "summary_status": "pending",
                "retry_count": 0,
            },
        ]
    )
    conn.execute("UPDATE segments SET heading_path = NULL WHERE id = 'hp1'")
    conn.commit()
    catalog = SegmentRepo(conn).list_catalog("hp")
    assert catalog[0]["heading_path"] == ["第一部分", "第一章"]
    assert catalog[1]["heading_path"] == ["序言"]
    assert "raw_text" not in catalog[0]
    assert "summary_json" not in catalog[0]
    conn.close()


def test_list_catalog_ignores_summary_json_when_not_ready(tmp_path):
    conn = init_db(tmp_path / "pending-catalog.db")
    conn.execute(
        "INSERT INTO books (id, title, format, file_path, created_at, updated_at) "
        "VALUES ('pend', 't', 'txt', '/x', 'now', 'now')"
    )
    SegmentRepo(conn).insert_many(
        [
            {
                "id": "pend-s",
                "book_id": "pend",
                "idx": 0,
                "chapter": None,
                "page_range": None,
                "anchor_label": "a",
                "raw_text": "hello",
                "summary_status": "pending",
                "retry_count": 0,
            }
        ]
    )
    conn.execute(
        "UPDATE segments SET summary_json = ? WHERE id = 'pend-s'",
        ('{"sentences":["不该出现在未摘要段的预览"]}',),
    )
    conn.commit()
    catalog = SegmentRepo(conn).list_catalog("pend")
    assert "summary_json" not in catalog[0]
    assert catalog[0].get("summary_preview") is None
    conn.close()


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
    # Default auto_start_summary is off; start prefetch explicitly.
    assert client.post(f"/books/{book_id}/summarize/start").status_code == 200
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


def test_health_responds_while_open_book_waits_on_database(client, monkeypatch):
    """Opening another book must not block the sidecar event loop."""
    import time

    book_id = import_sample_book(client)
    original_update = BookRepo.update

    def slow_update(self, target_book_id, **fields):
        if target_book_id == book_id and "last_opened_at" in fields:
            time.sleep(0.2)
        return original_update(self, target_book_id, **fields)

    monkeypatch.setattr(BookRepo, "update", slow_update)

    worker = threading.Thread(target=lambda: client.post(f"/books/{book_id}/open"))
    worker.start()
    time.sleep(0.05)
    health = client.get("/health").json()["status"]
    worker.join(timeout=5)

    assert worker.is_alive() is False
    assert health == "ok"


def test_context_probe_handler_does_not_block_health(client):
    """POST /context-probe must return before LLM rungs finish."""
    import time

    client.app.state.lumina.router.pinned_delay_s = 1.5
    health_during: list[str] = []

    def start_probe() -> None:
        client.post("/settings/resources/ollama/context-probe", json={})

    worker = threading.Thread(target=start_probe)
    worker.start()
    time.sleep(0.05)
    health_during.append(client.get("/health").json()["status"])
    worker.join(timeout=5)
    client.post("/settings/resources/ollama/context-probe/cancel")
    assert worker.is_alive() is False
    assert health_during == ["ok"]


def test_health_responds_while_ingest_extracts(client, monkeypatch):
    """Ingest CPU work must yield so /health stays on the event loop."""
    import time

    from lumina_core.ingest import txt_persist as txt_persist_module

    entered = threading.Event()
    orig = txt_persist_module.persist_streamed_txt_ingest

    def slow_persist(*args, **kwargs):
        entered.set()
        time.sleep(0.3)
        cancel = kwargs.get("cancel_event")
        if cancel is not None and cancel.is_set():
            from lumina_core.ingest.progress import DocumentLoadCancelled

            raise DocumentLoadCancelled("已取消")
        return orig(*args, **kwargs)

    monkeypatch.setattr(txt_persist_module, "persist_streamed_txt_ingest", slow_persist)
    sample = BOOK_FIXTURES / "sample.txt"
    book_id = client.post("/books/import", json={"paths": [str(sample)]}).json()["books"][0][
        "book_id"
    ]
    assert entered.wait(timeout=2)
    health = client.get("/health").json()["status"]
    wait_for_ingest(client, book_id, timeout=5.0)
    assert health == "ok"


def test_health_responds_while_summarize_indexes(client, monkeypatch):
    """FTS index after a segment summary must not block the sidecar event loop."""
    import time

    from lumina_core.search import fts as fts_module

    book_id = import_sample_book(client)
    orig_index = fts_module.index_segment
    entered = threading.Event()

    def slow_index_segment(conn, book, seg):
        entered.set()
        time.sleep(0.3)
        return orig_index(conn, book, seg)

    monkeypatch.setattr(fts_module, "index_segment", slow_index_segment)
    assert client.post(f"/books/{book_id}/summarize/start").status_code == 200
    assert entered.wait(timeout=5)
    started = time.monotonic()
    health = client.get("/health").json()["status"]
    elapsed = time.monotonic() - started
    assert health == "ok"
    # Bound proves /health did not wait on the 0.3s FTS stall; allow suite load.
    assert elapsed < 0.5


def test_health_responds_while_next_summary_waits_for_database(client, monkeypatch):
    """Summary continuation may wait for SQLite, but the event loop must not."""
    import asyncio
    import time

    queue = client.app.state.lumina.job_queue  # type: ignore[attr-defined]
    entered = threading.Event()
    release = threading.Event()
    original = queue._segments_repo.next_incomplete_segment

    def blocked_next(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=5)
        return original(*args, **kwargs)

    monkeypatch.setattr(queue._segments_repo, "next_incomplete_segment", blocked_next)
    worker = threading.Thread(
        target=lambda: asyncio.run(queue._enqueue_next_book_summary("missing-book"))
    )
    worker.start()
    assert entered.wait(timeout=2)
    started = time.monotonic()
    health = client.get("/health")
    elapsed = time.monotonic() - started
    release.set()
    worker.join(timeout=5)

    assert worker.is_alive() is False
    assert health.json()["status"] == "ok"
    # Bound proves /health did not wait on the held DB call (up to 5s); 0.15
    # flakes under full-suite load (~0.26s observed).
    assert elapsed < 0.5


def test_health_responds_during_segment_summary_prefetch_fanout(client, monkeypatch):
    """A segment jump's summary fan-out must not starve /health."""
    import time

    book_id = import_sample_book(client)
    original = SegmentRepo.get_summary_by_index
    entered = threading.Event()

    def slow_summary(self, target_book_id, idx):
        entered.set()
        time.sleep(0.3)
        return original(self, target_book_id, idx)

    monkeypatch.setattr(SegmentRepo, "get_summary_by_index", slow_summary)
    workers = [
        threading.Thread(
            target=lambda idx=idx: client.get(
                f"/books/{book_id}/segments/{idx}/summary"
            )
        )
        for idx in range(7)
    ]
    for worker in workers:
        worker.start()
    assert entered.wait(timeout=2)
    started = time.monotonic()
    health = client.get("/health")
    elapsed = time.monotonic() - started
    for worker in workers:
        worker.join(timeout=5)

    assert all(not worker.is_alive() for worker in workers)
    assert health.json()["status"] == "ok"
    # Bound proves /health did not wait on the 0.3s summary stall; allow suite load.
    assert elapsed < 0.5


def test_list_catalog_never_parses_summary_json_fallback(tmp_path, monkeypatch):
    """Opening a legacy book must use caches, never parse every summary inline."""
    conn = init_db(tmp_path / "catalog-cache.db")
    BookRepo(conn).insert(
        id="cached-book",
        title="Cached",
        format="txt",
        file_path="/tmp/cached.txt",
        segment_count=1,
        status="reading",
    )
    SegmentRepo(conn).insert_many(
        [
            {
                "id": "cached-segment",
                "book_id": "cached-book",
                "idx": 0,
                "raw_text": "正文",
                "summary_status": "ready",
            }
        ]
    )
    summary_json = (
        '{"sentences":["缓存首句。"],'
        '"bullets":[{"label":"缓存标签","body":"正文"}]}'
    )
    with conn:
        conn.execute(
            """
            UPDATE segments
            SET summary_json = ?, summary_preview = NULL, bullet_labels = NULL
            WHERE id = 'cached-segment'
            """,
            (summary_json,),
        )

    def fail_if_parsed(_value):
        raise AssertionError("list_catalog parsed summary_json")

    monkeypatch.setattr("lumina_core.db.repos.segment_list_fields", fail_if_parsed)
    catalog = SegmentRepo(conn).list_catalog("cached-book")
    assert "summary_json" not in catalog[0]
    assert "summary_preview" not in catalog[0]
    assert "bullet_labels" not in catalog[0]
    conn.close()


def test_backfill_catalog_cache_populates_legacy_rows(tmp_path):
    conn = init_db(tmp_path / "catalog-backfill.db")
    BookRepo(conn).insert(
        id="legacy-book",
        title="Legacy",
        format="txt",
        file_path="/tmp/legacy.txt",
        segment_count=1,
        status="reading",
    )
    SegmentRepo(conn).insert_many(
        [
            {
                "id": "legacy-segment",
                "book_id": "legacy-book",
                "idx": 0,
                "raw_text": "正文",
                "summary_status": "ready",
            }
        ]
    )
    with conn:
        conn.execute(
            """
            UPDATE segments
            SET summary_json = ?, summary_preview = NULL, bullet_labels = NULL
            WHERE id = 'legacy-segment'
            """,
            (
                '{"sentences":["旧书首句。"],'
                '"bullets":[{"label":"旧书标签","body":"正文"}]}',
            ),
        )
    assert SegmentRepo(conn).backfill_catalog_cache(batch_size=1) == 1
    catalog = SegmentRepo(conn).list_catalog("legacy-book")
    assert catalog[0]["summary_preview"] == "旧书首句。"
    assert catalog[0]["bullet_labels"] == ["旧书标签"]
    conn.close()


def test_backfill_prefix_labels_fills_empty_from_sentence(tmp_path):
    conn = init_db(tmp_path / "prefix-label-backfill.db")
    BookRepo(conn).insert(
        id="prefix-book",
        title="Prefix",
        format="txt",
        file_path="/tmp/prefix.txt",
        segment_count=1,
        status="reading",
    )
    SegmentRepo(conn).insert_many(
        [
            {
                "id": "prefix-segment",
                "book_id": "prefix-book",
                "idx": 0,
                "raw_text": "正文",
                "summary_status": "ready",
                "label": None,
                "anchor_label": "§第一章 · 段 1",
            }
        ]
    )
    with conn:
        conn.execute(
            """
            UPDATE segments
            SET summary_json = ?, label = NULL
            WHERE id = 'prefix-segment'
            """,
            (
                '{"sentences":["本段交代主角寒门出身与赴考之志。"],'
                '"bullets":[{"label":"寒门出身","body":"主角生于贫苦农家。"},'
                '{"label":"赴考之志","body":"段末誓要金榜题名。"},'
                '{"label":"邻里关系","body":"邻里敬其向学。"}]}',
            ),
        )
    assert SegmentRepo(conn).backfill_prefix_labels(batch_size=1) == 1
    catalog = SegmentRepo(conn).list_catalog("prefix-book")
    assert catalog[0]["label"] == "本段交代主角寒门"
    assert " · " not in catalog[0]["label"]
    assert SegmentRepo(conn).backfill_prefix_labels(batch_size=1) == 0
    conn.close()


def test_backfill_queries_use_partial_indexes(tmp_path):
    conn = init_db(tmp_path / "idx-test.db")
    cur = conn.cursor()
    q1 = """
    EXPLAIN QUERY PLAN
    SELECT id, summary_json
    FROM segments
    WHERE summary_status = 'ready'
      AND summary_json IS NOT NULL
      AND (summary_preview IS NULL OR bullet_labels IS NULL)
    ORDER BY book_id, idx
    LIMIT 64
    """
    plan1 = " ".join(" ".join(str(v) for v in row) for row in cur.execute(q1).fetchall())
    assert "idx_segments_backfill_catalog" in plan1

    q2 = """
    EXPLAIN QUERY PLAN
    SELECT id, label, summary_json, anchor_label
    FROM segments
    WHERE summary_status = 'ready'
      AND summary_json IS NOT NULL
      AND (label IS NULL OR TRIM(label) = '')
      AND id > ?
    ORDER BY id
    LIMIT 64
    """
    plan2 = " ".join(" ".join(str(v) for v in row) for row in cur.execute(q2, ("",)).fetchall())
    assert "idx_segments_backfill_prefix" in plan2
    conn.close()


def test_health_and_books_respond_during_cpu_bound_ingest(client, monkeypatch):
    """Python CPU in ingest must yield the GIL so /health and GET /books stay live."""
    import time

    from lumina_core.chunker.coop import GilYielder
    from lumina_core.ingest import txt_persist as txt_persist_module

    entered = threading.Event()
    still_busy = threading.Event()
    still_busy.set()
    orig = txt_persist_module.persist_streamed_txt_ingest

    def busy_persist(*args, **kwargs):
        entered.set()
        yielder = GilYielder(kwargs.get("cancel_event"), every=4_000)
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            yielder.bump(1)
        still_busy.clear()
        return orig(*args, **kwargs)

    monkeypatch.setattr(txt_persist_module, "persist_streamed_txt_ingest", busy_persist)
    sample = BOOK_FIXTURES / "sample.txt"
    book_id = client.post("/books/import", json={"paths": [str(sample)]}).json()["books"][0][
        "book_id"
    ]
    assert entered.wait(timeout=5)
    started = time.monotonic()
    health = client.get("/health").json()["status"]
    health_elapsed = time.monotonic() - started
    books = client.get("/books")
    assert health == "ok"
    assert still_busy.is_set(), "GET /health waited for the ingest CPU loop to finish"
    # Bound proves /health did not wait out the 1s CPU loop; allow suite load.
    assert health_elapsed < 0.5
    assert books.status_code == 200
    listed = next(b for b in books.json()["books"] if b["id"] == book_id)
    assert "metadata_json" not in listed
    wait_for_ingest(client, book_id, timeout=15.0)


def test_ingest_cpu_jobs_run_one_at_a_time(client, monkeypatch, tmp_path):
    """TDD CPU queue concurrency 1: second ingest must not start extract until the first yields."""
    from lumina_core.ingest import txt_persist as txt_persist_module

    started: list[str] = []
    first_entered = threading.Event()
    release_first = threading.Event()
    orig = txt_persist_module.persist_streamed_txt_ingest

    def tracking_persist(db_path, **kwargs):
        started.append(str(kwargs.get("dest")))
        if len(started) == 1:
            first_entered.set()
            assert release_first.wait(timeout=8)
        return orig(db_path, **kwargs)

    monkeypatch.setattr(txt_persist_module, "persist_streamed_txt_ingest", tracking_persist)
    first = tmp_path / "one.txt"
    second = tmp_path / "two.txt"
    first.write_text("alpha", encoding="utf-8")
    second.write_text("beta", encoding="utf-8")
    resp = client.post("/books/import", json={"paths": [str(first), str(second)]})
    assert resp.status_code == 200
    ids = [row["book_id"] for row in resp.json()["books"]]
    assert first_entered.wait(timeout=5)
    client.get("/health")
    assert len(started) == 1
    release_first.set()
    for book_id in ids:
        wait_for_ingest(client, book_id, timeout=15.0)
    assert len(started) == 2


def test_other_book_segments_respond_during_large_txt_chunk(client):
    """Opening another book (GET /segments) must work while a large TXT is chunking."""
    import time

    from lumina_core.chunker.chunker import chunk_text

    other_id = import_sample_book(client)
    line = "　　这是一段用于测试超大 TXT 导入的中文句子，保证每段都有句号。\n"
    bulky = "第一章 开篇\n\n" + line * 3500
    started = threading.Event()
    finished = threading.Event()

    def run_chunk() -> None:
        started.set()
        chunk_text(bulky)
        finished.set()

    worker = threading.Thread(target=run_chunk)
    worker.start()
    assert started.wait(timeout=5)
    time.sleep(0.02)
    t0 = time.monotonic()
    listed = client.get(f"/books/{other_id}/segments")
    elapsed = time.monotonic() - t0
    health = client.get("/health").json()["status"]
    worker.join(timeout=20)
    assert listed.status_code == 200
    assert listed.json()["segments"]
    assert health == "ok"
    assert elapsed < 0.4, elapsed
    assert finished.is_set()


def test_should_offload_cpu_respects_size_and_inline_env(tmp_path, monkeypatch):
    from lumina_core.jobs.cpu_worker import (
        CPU_PROCESS_MIN_BYTES,
        INLINE_ENV,
        cpu_worker_command,
        should_offload_cpu,
    )

    small = tmp_path / "small.txt"
    small.write_bytes(b"x" * 16)
    bulky = tmp_path / "bulky.txt"
    bulky.write_bytes(b"x" * CPU_PROCESS_MIN_BYTES)
    monkeypatch.delenv(INLINE_ENV, raising=False)
    assert should_offload_cpu(small) is False
    assert should_offload_cpu(bulky) is True
    monkeypatch.setenv(INLINE_ENV, "1")
    assert should_offload_cpu(bulky) is False
    cmd = cpu_worker_command(tmp_path / "job.json")
    assert "-m" in cmd
    assert "lumina_core.jobs.cpu_worker" in cmd


def test_health_news_settings_other_book_live_during_cpu_process_ingest(
    client, tmp_path
):
    """A ≥256KiB TXT must ingest in a child process so news/settings/other books stay live."""
    import time

    from lumina_core.jobs.cpu_worker import CPU_PROCESS_MIN_BYTES

    other_id = import_sample_book(client)
    line = "　　双方继续对峙，这是一段用于测试导入时界面仍可点的中文句子。\n"
    header = "第一章 开篇\n\n"
    chunks = [header]
    size = len(header.encode("utf-8"))
    encoded_line = line.encode("utf-8")
    while size < CPU_PROCESS_MIN_BYTES + 4096:
        chunks.append(line)
        size += len(encoded_line)
    bulky = tmp_path / "huge.txt"
    bulky.write_text("".join(chunks), encoding="utf-8")

    big_id = client.post("/books/import", json={"paths": [str(bulky)]}).json()["books"][
        0
    ]["book_id"]
    deadline = time.time() + 90
    saw_processing = False
    last: dict = {}
    while time.time() < deadline:
        last = client.get(f"/books/{big_id}").json()
        status = last.get("status")
        started = time.monotonic()
        health = client.get("/health")
        news = client.get("/news/sources")
        settings = client.get("/settings")
        segs = client.get(f"/books/{other_id}/segments")
        opened = client.post(f"/books/{other_id}/open")
        elapsed = time.monotonic() - started
        if status == "processing":
            saw_processing = True
            assert health.status_code == 200
            assert health.json()["status"] == "ok"
            assert news.status_code == 200
            assert "sources" in news.json()
            assert settings.status_code == 200
            assert segs.status_code == 200
            assert segs.json()["segments"]
            assert opened.status_code == 200
            assert elapsed < 0.8, elapsed
        elif status == "error":
            raise AssertionError(f"ingest failed: {last}")
        elif status not in (None, "processing"):
            if (last.get("segment_count") or 0) > 0:
                listed = client.get(f"/books/{big_id}/segments").json()["segments"]
                if listed:
                    break
        time.sleep(0.05)
    else:
        raise AssertionError(f"cpu-process ingest timed out: {last}")
    assert saw_processing
    wait_for_ingest(client, big_id, timeout=30.0)


def test_cpu_worker_parent_kills_stalled_child(tmp_path, monkeypatch):
    import sys
    import time

    from lumina_core.jobs import cpu_worker as cw

    def fake_cmd(_job_path):
        script = (
            "import json, sys, time\n"
            "print(json.dumps({'type':'progress','page':1,'total':10,"
            "'message':'正在解析文档…'}, ensure_ascii=False), flush=True)\n"
            "time.sleep(30)\n"
            "print(json.dumps({'type':'done','segment_count':1}), flush=True)\n"
        )
        return [sys.executable, "-c", script]

    monkeypatch.setattr(cw, "cpu_worker_command", fake_cmd)
    monkeypatch.setenv(cw.STALL_ENV, "0.4")
    monkeypatch.setenv(cw.JOB_MAX_ENV, "30")
    cancel = threading.Event()
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="分段超时"):
        cw.run_cpu_worker_sync(
            {"book_id": "b1", "kind": "ingest"},
            cancel,
            None,
            tmp_path / "data",
        )
    assert time.monotonic() - started < 8


def test_cpu_job_max_seconds_scales_with_pages_and_file_size():
    from lumina_core.jobs.cpu_worker import (
        cpu_job_max_seconds,
        page_count_from_progress,
    )

    mib = 1024 * 1024
    assert cpu_job_max_seconds(file_bytes=1024, page_count=None) == 1800.0
    assert cpu_job_max_seconds(file_bytes=5 * mib, page_count=200) == 200 * 60
    assert cpu_job_max_seconds(file_bytes=100 * mib, page_count=None) == 100 * 30
    assert cpu_job_max_seconds(file_bytes=0, page_count=2000) == 8 * 3600
    assert (
        page_count_from_progress("pdf", 200, "扫描版 PDF · 本地 OCR 1/200 页…") == 200
    )
    assert page_count_from_progress("pdf", 320, "正在解析 PDF（共 320 页）…") == 320
    assert (
        page_count_from_progress("epub", 560, "图片型 EPUB · 本地 OCR 1/560 页…")
        == 560
    )
    assert page_count_from_progress("txt", 200, "扫描版 PDF · 本地 OCR 1/200 页…") is None
    assert page_count_from_progress("pdf", 5000, "正在识别序言与正文结构…") is None


def test_cpu_worker_pdf_page_progress_extends_job_max(tmp_path, monkeypatch):
    import sys
    import time

    from lumina_core.jobs import cpu_worker as cw

    monkeypatch.setattr(cw, "CPU_JOB_MAX_FLOOR_SECONDS", 0.35)
    monkeypatch.setattr(cw, "CPU_JOB_SECONDS_PER_PAGE", 1.5)
    monkeypatch.setattr(cw, "CPU_JOB_MAX_CEILING_SECONDS", 30.0)
    monkeypatch.delenv(cw.JOB_MAX_ENV, raising=False)
    monkeypatch.setenv(cw.STALL_ENV, "20")

    def fake_cmd(_job_path):
        script = (
            "import json, sys, time\n"
            "print(json.dumps({'type':'progress','page':1,'total':10,"
            "'message':'扫描版 PDF · 本地 OCR 1/10 页…'}, ensure_ascii=False), flush=True)\n"
            "time.sleep(0.9)\n"
            "print(json.dumps({'type':'done','segment_count':1}), flush=True)\n"
        )
        return [sys.executable, "-c", script]

    monkeypatch.setattr(cw, "cpu_worker_command", fake_cmd)
    started = time.monotonic()
    result = cw.run_cpu_worker_sync(
        {"book_id": "b1", "kind": "ingest", "fmt": "pdf", "page_count": 10},
        threading.Event(),
        None,
        tmp_path / "data",
    )
    assert result["segment_count"] == 1
    assert time.monotonic() - started < 8


def test_cpu_worker_txt_char_progress_does_not_count_as_pages(tmp_path, monkeypatch):
    import sys
    import time

    from lumina_core.jobs import cpu_worker as cw

    monkeypatch.setattr(cw, "CPU_JOB_MAX_FLOOR_SECONDS", 0.4)
    monkeypatch.setattr(cw, "CPU_JOB_SECONDS_PER_PAGE", 60.0)
    monkeypatch.delenv(cw.JOB_MAX_ENV, raising=False)
    monkeypatch.setenv(cw.STALL_ENV, "20")

    def fake_cmd(_job_path):
        script = (
            "import json, sys, time\n"
            "print(json.dumps({'type':'progress','page':1000,'total':99999,"
            "'message':'正在识别序言与正文结构…'}, ensure_ascii=False), flush=True)\n"
            "time.sleep(8)\n"
            "print(json.dumps({'type':'done','segment_count':1}), flush=True)\n"
        )
        return [sys.executable, "-c", script]

    monkeypatch.setattr(cw, "cpu_worker_command", fake_cmd)
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="分段超时：单本处理超过"):
        cw.run_cpu_worker_sync(
            {"book_id": "b1", "kind": "ingest", "fmt": "txt"},
            threading.Event(),
            None,
            tmp_path / "data",
        )
    assert time.monotonic() - started < 4


def test_queued_ingest_emits_wait_progress():
    import asyncio
    from types import SimpleNamespace

    from lumina_core.api.routes import _await_cpu_lock

    async def run() -> None:
        lock = asyncio.Semaphore(1)
        await lock.acquire()
        queue: asyncio.Queue = asyncio.Queue()
        state = SimpleNamespace(
            cpu_job_lock=lock,
            event_subscribers={"b-wait": [queue]},
        )
        task = asyncio.create_task(_await_cpu_lock(state, "b-wait"))
        first = await asyncio.wait_for(queue.get(), timeout=1)
        assert first.get("message") == "排队等待分段…"
        second = await asyncio.wait_for(queue.get(), timeout=2)
        assert second.get("message") == "排队等待分段…"
        lock.release()
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(run())


def test_list_books_does_not_call_summarize_state_by_book(client):
    """GET /books must not N+1-scan the library on the event loop."""
    queue = client.app.state.lumina.job_queue

    def boom():
        raise AssertionError("summarize_state_by_book must not run on GET /books")

    queue.summarize_state_by_book = boom  # type: ignore[method-assign]
    assert client.get("/books").status_code == 200


def test_open_book_does_not_await_prefetch(client, monkeypatch):
    """POST /open must return before auto-start prefetch finishes."""
    import asyncio
    import time

    book_id = import_sample_book(client)
    queue = client.app.state.lumina.job_queue
    queue.auto_start_summary = True
    entered = threading.Event()
    release = threading.Event()
    original = queue.enqueue_book_prefetch

    async def slow_prefetch(bid, **kwargs):
        entered.set()
        assert await asyncio.to_thread(release.wait, 5)
        return await original(bid, **kwargs)

    monkeypatch.setattr(queue, "enqueue_book_prefetch", slow_prefetch)
    started = time.monotonic()
    resp = client.post(f"/books/{book_id}/open")
    elapsed = time.monotonic() - started
    assert resp.status_code == 200
    assert resp.json()["status"] == "opened"
    # Prefetch is intentionally blocked for up to 5s; open must not wait.
    assert elapsed < 0.75
    assert entered.wait(timeout=2)
    release.set()


def test_segment_repo_point_queries_skip_full_scan(tmp_path):
    """Hot-path helpers must not require loading every segment."""
    conn = init_db(tmp_path / "point.db")
    book_id = "big-book"
    BookRepo(conn).insert(
        id=book_id,
        title="Big",
        format="txt",
        file_path="/tmp/b.txt",
        segment_count=3000,
        status="unread",
    )
    segs = [
        {
            "id": f"s-{i}",
            "book_id": book_id,
            "idx": i,
            "anchor_label": f"段 {i + 1}",
            "raw_text": f"正文 {i}",
            "summary_status": "ready" if i < 2990 else "pending",
            "retry_count": 0,
            "summary_tier": "normal",
        }
        for i in range(3000)
    ]
    segs[10]["summary_status"] = "running"
    segs[11]["summary_status"] = "error"
    SegmentRepo(conn).insert_many(segs)
    repo = SegmentRepo(conn)

    nxt = repo.next_incomplete_segment(book_id)
    assert nxt is not None
    assert nxt["idx"] == 11  # error before later pending

    running = repo.list_running_segments(book_id)
    assert [r["idx"] for r in running] == [10]

    reset = repo.reset_running_segments(book_id)
    assert [r["idx"] for r in reset] == [10]
    assert repo.get("s-10")["summary_status"] == "pending"

    failed = repo.reset_failed_segments(book_id)
    assert any(s["idx"] == 11 for s in failed)
    assert repo.get("s-11")["summary_status"] == "pending"

    n = repo.apply_summary_tier_to_incomplete(book_id, "advanced")
    assert n >= 1
    assert repo.get("s-2990")["summary_tier"] == "advanced"
    # Ready rows keep their tier.
    assert (repo.get("s-0").get("summary_tier") or "normal") == "normal"
    conn.close()
