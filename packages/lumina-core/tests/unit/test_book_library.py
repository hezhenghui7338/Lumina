"""Book library repo/API tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from lumina_core.db.repos import BookRepo, NoteRepo, SegmentRepo, reading_progress_bucket
from lumina_core.db.schema import init_db


def _insert_book(conn, **overrides):
    repo = BookRepo(conn)
    book_id = overrides.pop("id", str(uuid.uuid4()))
    now = datetime.now(timezone.utc).isoformat()
    defaults = {
        "id": book_id,
        "title": overrides.pop("title", f"Book {book_id[:8]}"),
        "format": "txt",
        "file_path": f"/tmp/{book_id}.txt",
        "status": "unread",
        "segment_count": 1,
        "file_hash": book_id,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    conn.execute(
        """
        INSERT INTO books (
          id, title, author, format, file_path, segment_count, current_segment_index,
          status, file_hash, metadata_json, is_favorite, category, last_opened_at,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?, ?, ?, ?)
        """,
        (
            defaults["id"],
            defaults["title"],
            defaults.get("author"),
            defaults["format"],
            defaults["file_path"],
            defaults["segment_count"],
            defaults.get("current_segment_index", 0),
            defaults["status"],
            defaults["file_hash"],
            defaults.get("is_favorite", 0),
            defaults.get("category"),
            defaults.get("last_opened_at"),
            defaults["created_at"],
            defaults["updated_at"],
        ),
    )
    conn.commit()
    return repo.get(book_id)


@pytest.fixture
def db_conn(tmp_path):
    return init_db(tmp_path / "library.db")


def test_list_books_filter_and_sort(db_conn):
    repo = BookRepo(db_conn)
    a = _insert_book(
        db_conn,
        title="Alpha",
        status="unread",
        category="文学",
        is_favorite=0,
        created_at="2024-01-01T00:00:00+00:00",
        last_opened_at=None,
    )
    _insert_book(
        db_conn,
        title="Beta",
        status="reading",
        category="历史",
        is_favorite=1,
        created_at="2024-02-01T00:00:00+00:00",
        last_opened_at="2024-03-01T00:00:00+00:00",
    )
    gamma = _insert_book(
        db_conn,
        title="Gamma",
        status="summarized",
        category="科技",
        is_favorite=0,
        created_at="2024-04-01T00:00:00+00:00",
        last_opened_at="2024-05-01T00:00:00+00:00",
    )
    unclassified = _insert_book(
        db_conn,
        title="Unclassified",
        status="unread",
        category=None,
    )

    literature = repo.list_books(filter="文学")
    assert [b["id"] for b in literature] == [a["id"]]

    summarized = repo.list_books(filter="summarized")
    assert [b["id"] for b in summarized] == [gamma["id"]]

    history = repo.list_books(filter="历史")
    assert [b["title"] for b in history] == ["Beta"]

    assert unclassified["id"] not in {b["id"] for b in literature}
    assert unclassified["id"] in {b["id"] for b in repo.list_books(filter="all")}

    by_title = repo.list_books(sort="title")
    assert [b["title"] for b in by_title] == ["Alpha", "Beta", "Gamma", "Unclassified"]

    favorites = repo.list_books(sort="favorite")
    assert favorites[0]["title"] == "Beta"


def test_reading_progress_bucket_ignores_status_summarized():
    unread = {"last_opened_at": None, "segment_count": 10, "current_segment_index": 0}
    reading = {
        "last_opened_at": "2024-05-01T00:00:00+00:00",
        "segment_count": 10,
        "current_segment_index": 3,
        "status": "summarized",
    }
    finished = {
        "last_opened_at": "2024-05-01T00:00:00+00:00",
        "segment_count": 10,
        "current_segment_index": 9,
    }
    short_opened = {
        "last_opened_at": "2024-05-01T00:00:00+00:00",
        "segment_count": 1,
        "current_segment_index": 0,
    }
    assert reading_progress_bucket(unread) == "unread"
    assert reading_progress_bucket(reading) == "reading"
    assert reading_progress_bucket(finished) == "finished"
    assert reading_progress_bucket(short_opened) == "reading"


def test_list_books_reading_progress_and_favorite_filters(db_conn):
    repo = BookRepo(db_conn)
    unread = _insert_book(
        db_conn,
        title="Unread",
        last_opened_at=None,
        segment_count=8,
        current_segment_index=0,
        status="unread",
    )
    reading = _insert_book(
        db_conn,
        title="Reading",
        last_opened_at="2024-05-01T00:00:00+00:00",
        segment_count=8,
        current_segment_index=2,
        status="summarized",
        is_favorite=1,
    )
    finished = _insert_book(
        db_conn,
        title="Finished",
        last_opened_at="2024-06-01T00:00:00+00:00",
        segment_count=8,
        current_segment_index=7,
        status="summarized",
    )
    short = _insert_book(
        db_conn,
        title="ShortOpened",
        last_opened_at="2024-07-01T00:00:00+00:00",
        segment_count=1,
        current_segment_index=0,
        status="reading",
    )

    assert {b["title"] for b in repo.list_books(filter="unread")} == {"Unread"}
    assert {b["title"] for b in repo.list_books(filter="reading")} == {"Reading", "ShortOpened"}
    assert {b["title"] for b in repo.list_books(filter="finished")} == {"Finished"}
    assert [b["title"] for b in repo.list_books(filter="favorite")] == ["Reading"]
    assert unread["id"] in {b["id"] for b in repo.list_books(filter="all")}
    assert reading["id"] in {b["id"] for b in repo.list_books(filter="all")}
    assert finished["id"] in {b["id"] for b in repo.list_books(filter="all")}
    assert short["id"] in {b["id"] for b in repo.list_books(filter="reading")}


def test_list_books_sort_by_segment_count(db_conn):
    repo = BookRepo(db_conn)
    _insert_book(db_conn, title="Short", segment_count=3)
    _insert_book(db_conn, title="Long", segment_count=40)
    _insert_book(db_conn, title="Mid", segment_count=12)

    titles = [b["title"] for b in repo.list_books(sort="segments")]
    assert titles == ["Long", "Mid", "Short"]


def test_delete_removes_fts(db_conn):
    repo = BookRepo(db_conn)
    book = _insert_book(db_conn, title="Delete Me")
    db_conn.execute(
        """
        INSERT INTO search_fts (book_id, segment_id, note_id, kind, title, body)
        VALUES (?, NULL, NULL, 'book', ?, ?)
        """,
        (book["id"], book["title"], ""),
    )
    db_conn.commit()

    repo.delete(book["id"])
    row = db_conn.execute(
        "SELECT COUNT(*) AS c FROM search_fts WHERE book_id = ?",
        (book["id"],),
    ).fetchone()
    assert row["c"] == 0


def test_delete_removes_segments_and_notes(db_conn):
    repo = BookRepo(db_conn)
    book = _insert_book(db_conn, title="Delete Me")
    seg_id = str(uuid.uuid4())
    db_conn.execute(
        """
        INSERT INTO segments (id, book_id, idx, raw_text, summary_status)
        VALUES (?, ?, 0, 'text', 'ready')
        """,
        (seg_id, book["id"]),
    )
    db_conn.commit()

    NoteRepo(db_conn).create(
        book_id=book["id"],
        segment_id=seg_id,
        content="note content",
    )

    repo.delete(book["id"])

    assert repo.get(book["id"]) is None
    seg_count = db_conn.execute(
        "SELECT COUNT(*) AS c FROM segments WHERE book_id = ?",
        (book["id"],),
    ).fetchone()["c"]
    note_count = db_conn.execute(
        "SELECT COUNT(*) AS c FROM notes WHERE book_id = ?",
        (book["id"],),
    ).fetchone()["c"]
    assert seg_count == 0
    assert note_count == 0


def test_maybe_mark_summarized(db_conn):
    repo = BookRepo(db_conn)
    book = _insert_book(db_conn, status="reading", segment_count=2)
    seg_repo = SegmentRepo(db_conn)
    for idx in range(2):
        seg_repo.insert_many(
            [
                {
                    "id": str(uuid.uuid4()),
                    "book_id": book["id"],
                    "idx": idx,
                    "raw_text": "text",
                    "summary_status": "ready" if idx == 0 else "pending",
                }
            ]
        )

    assert repo.maybe_mark_summarized(book["id"]) is False
    pending = seg_repo.list_for_book(book["id"], include_body=False)[1]
    seg_repo.set_status(pending["id"], "ready")
    assert repo.maybe_mark_summarized(book["id"]) is True
    assert repo.get(book["id"])["status"] == "summarized"


def test_summary_progress(db_conn):
    repo = BookRepo(db_conn)
    book = _insert_book(db_conn, status="reading", segment_count=3)
    seg_repo = SegmentRepo(db_conn)
    for idx, status in enumerate(["ready", "ready", "pending"]):
        seg_repo.insert_many(
            [
                {
                    "id": str(uuid.uuid4()),
                    "book_id": book["id"],
                    "idx": idx,
                    "raw_text": "text",
                    "char_count": 4,
                    "summary_status": status,
                }
            ]
        )

    progress = repo.summary_progress(book["id"])
    assert progress == {"summary_ready_count": 2, "summary_total_count": 3}


def test_maybe_mark_summarized_promotes_stale_reading(db_conn):
    """All segments ready but status still reading → promote to summarized."""
    repo = BookRepo(db_conn)
    book = _insert_book(db_conn, status="reading", segment_count=2)
    seg_repo = SegmentRepo(db_conn)
    for idx in range(2):
        seg_repo.insert_many(
            [
                {
                    "id": str(uuid.uuid4()),
                    "book_id": book["id"],
                    "idx": idx,
                    "raw_text": "text",
                    "summary_status": "ready",
                }
            ]
        )

    assert repo.get(book["id"])["status"] == "reading"
    assert repo.maybe_mark_summarized(book["id"]) is True
    assert repo.get(book["id"])["status"] == "summarized"

    summarized = repo.list_books(filter="summarized")
    assert [b["id"] for b in summarized] == [book["id"]]
