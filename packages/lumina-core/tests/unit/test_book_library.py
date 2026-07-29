"""Book library repo/API tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from lumina_core.db.repos import BookRepo, NoteRepo, SegmentRepo
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
          id, title, author, format, file_path, segment_count, status,
          file_hash, metadata_json, is_favorite, category, last_opened_at,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?, ?, ?, ?)
        """,
        (
            defaults["id"],
            defaults["title"],
            defaults.get("author"),
            defaults["format"],
            defaults["file_path"],
            defaults["segment_count"],
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
        is_favorite=0,
        created_at="2024-01-01T00:00:00+00:00",
        last_opened_at=None,
    )
    _insert_book(
        db_conn,
        title="Beta",
        status="reading",
        is_favorite=1,
        created_at="2024-02-01T00:00:00+00:00",
        last_opened_at="2024-03-01T00:00:00+00:00",
    )
    _insert_book(
        db_conn,
        title="Gamma",
        status="summarized",
        is_favorite=0,
        created_at="2024-04-01T00:00:00+00:00",
        last_opened_at="2024-05-01T00:00:00+00:00",
    )

    unread = repo.list_books(collection="unread")
    assert [b["id"] for b in unread] == [a["id"]]

    by_title = repo.list_books(sort="title")
    assert [b["title"] for b in by_title] == ["Alpha", "Beta", "Gamma"]

    favorites = repo.list_books(sort="favorite")
    assert favorites[0]["title"] == "Beta"


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

    summarized = repo.list_books(collection="summarized")
    assert [b["id"] for b in summarized] == [book["id"]]
