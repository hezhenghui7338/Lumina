"""Denormalized books.summary_* and O(1) summarize queued counts."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumina_core.config import Settings
from lumina_core.db.repos import BookRepo, SegmentRepo
from lumina_core.db.schema import init_db
from lumina_core.jobs.queue import JobItem, JobKind, JobQueue, _job_key
from lumina_core.main import create_app
from lumina_core.models.router import set_router
from tests.support.mock_router import MockModelRouter


@pytest.fixture
def db_conn(tmp_path):
    return init_db(tmp_path / "summary_progress.db")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMINA_DATA_DIR", str(tmp_path))
    router = MockModelRouter()
    app = create_app(Settings(data_dir=tmp_path))
    app.state.lumina.router = router
    app.state.lumina.job_queue.router = router
    set_router(router)
    with TestClient(app) as c:
        yield c


def _insert_book(conn: sqlite3.Connection, *, segment_count: int = 0) -> dict:
    return BookRepo(conn).insert(
        title="Cache Book",
        format="txt",
        file_path="/tmp/cache.txt",
        segment_count=segment_count,
        status="unread",
    )


def test_summary_progress_reads_denormalized_columns(db_conn):
    repo = BookRepo(db_conn)
    book = _insert_book(db_conn, segment_count=3)
    seg = SegmentRepo(db_conn)
    for idx, status in enumerate(["ready", "pending", "ready"]):
        seg.insert_many(
            [
                {
                    "id": str(uuid.uuid4()),
                    "book_id": book["id"],
                    "idx": idx,
                    "raw_text": "text",
                    "summary_status": status,
                }
            ]
        )

    progress = repo.summary_progress(book["id"])
    assert progress == {"summary_ready_count": 2, "summary_total_count": 3}
    row = repo.get(book["id"])
    assert int(row["summary_ready_count"]) == 2
    assert int(row["summary_total_count"]) == 3


def test_update_summary_bumps_ready_count(db_conn):
    repo = BookRepo(db_conn)
    book = _insert_book(db_conn, segment_count=1)
    seg_id = str(uuid.uuid4())
    SegmentRepo(db_conn).insert_many(
        [
            {
                "id": seg_id,
                "book_id": book["id"],
                "idx": 0,
                "raw_text": "text",
                "summary_status": "pending",
            }
        ]
    )
    assert repo.summary_progress(book["id"])["summary_ready_count"] == 0

    SegmentRepo(db_conn).update_summary(
        seg_id,
        summary_json='{"sentences":[{"text":"hi"}]}',
        label="hi",
        status="ready",
    )
    assert repo.summary_progress(book["id"]) == {
        "summary_ready_count": 1,
        "summary_total_count": 1,
    }


def test_list_books_does_not_count_segments_per_book(client, monkeypatch):
    """GET /books must use books.summary_* — not N× COUNT(segments)."""
    conn = client.app.state.lumina.conn
    book = BookRepo(conn).insert(
        title="Listed",
        format="txt",
        file_path="/tmp/listed.txt",
        segment_count=2,
        status="unread",
    )
    # Bypass insert_many recount so columns stay as planted.
    with conn:
        conn.execute(
            """
            INSERT INTO segments (
              id, book_id, idx, raw_text, char_count, summary_status, retry_count
            ) VALUES
              (?, ?, 0, 'a', 1, 'ready', 0),
              (?, ?, 1, 'b', 1, 'pending', 0)
            """,
            (str(uuid.uuid4()), book["id"], str(uuid.uuid4()), book["id"]),
        )
        conn.execute(
            """
            UPDATE books
            SET summary_ready_count = 1, summary_total_count = 2, segment_count = 2
            WHERE id = ?
            """,
            (book["id"],),
        )

    def boom(self, book_id: str):
        raise AssertionError(
            f"list_books must not recount segments for {book_id}"
        )

    monkeypatch.setattr(BookRepo, "refresh_summary_progress", boom)
    resp = client.get("/books")
    assert resp.status_code == 200
    listed = next(b for b in resp.json()["books"] if b["id"] == book["id"])
    assert listed["summary_ready_count"] == 1
    assert listed["summary_total_count"] == 2


def test_legacy_migrate_backfills_summary_progress(tmp_path: Path):
    db_path = tmp_path / "legacy_progress.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE books (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          author TEXT,
          format TEXT NOT NULL,
          file_path TEXT NOT NULL,
          segment_count INTEGER DEFAULT 0,
          status TEXT DEFAULT 'unread',
          file_hash TEXT,
          metadata_json TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE segments (
          id TEXT PRIMARY KEY,
          book_id TEXT NOT NULL,
          idx INTEGER NOT NULL,
          label TEXT,
          anchor_label TEXT,
          raw_text TEXT,
          summary_status TEXT DEFAULT 'pending',
          retry_count INTEGER DEFAULT 0
        );
        """
    )
    conn.execute(
        """
        INSERT INTO books (
          id, title, format, file_path, segment_count, status,
          metadata_json, created_at, updated_at
        ) VALUES ('b1', 'Old', 'txt', '/t', 2, 'unread', '{}', 't', 't')
        """
    )
    conn.execute(
        """
        INSERT INTO segments (id, book_id, idx, raw_text, summary_status)
        VALUES ('s1', 'b1', 0, 'a', 'ready'), ('s2', 'b1', 1, 'b', 'pending')
        """
    )
    conn.commit()
    conn.close()

    upgraded = init_db(db_path)
    row = upgraded.execute(
        "SELECT summary_ready_count, summary_total_count FROM books WHERE id = 'b1'"
    ).fetchone()
    assert int(row["summary_ready_count"]) == 1
    assert int(row["summary_total_count"]) == 2
    upgraded.close()


def test_summarize_queued_count_is_o1(db_conn):
    router = MockModelRouter()
    set_router(router)
    q = JobQueue(db_conn, router)
    book_a = "book-a"
    book_b = "book-b"
    # Plant many queued summarize keys without going through async enqueue.
    for i in range(200):
        item = JobItem(
            priority=i,
            book_id=book_a,
            segment_id=f"sa-{i}",
            segment_idx=i,
            kind=JobKind.SUMMARIZE,
        )
        q._add_queued_key(_job_key(item))
    for i in range(5):
        item = JobItem(
            priority=i,
            book_id=book_b,
            segment_id=f"sb-{i}",
            segment_idx=i,
            kind=JobKind.SUMMARIZE,
        )
        q._add_queued_key(_job_key(item))
    # Translate keys must not inflate summarize counts.
    q._add_queued_key(
        _job_key(
            JobItem(
                priority=0,
                book_id=book_a,
                segment_id="ta-0",
                segment_idx=0,
                kind=JobKind.TRANSLATE,
            )
        )
    )

    assert q._summarize_queued_count_for_book(book_a) == 200
    assert q._summarize_queued_count_for_book(book_b) == 5
    q._discard_queued_key(
        _job_key(
            JobItem(
                priority=0,
                book_id=book_a,
                segment_id="sa-0",
                segment_idx=0,
                kind=JobKind.SUMMARIZE,
            )
        )
    )
    assert q._summarize_queued_count_for_book(book_a) == 199
    q._clear_queued_keys()
    assert q._summarize_queued_count_for_book(book_a) == 0
