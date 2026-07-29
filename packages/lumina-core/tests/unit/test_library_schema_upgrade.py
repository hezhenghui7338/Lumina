"""Regression: legacy SQLite schema upgrades must not break library/reader APIs."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumina_core.config import Settings
from lumina_core.db.repos import BookRepo
from lumina_core.db.schema import init_db
from lumina_core.main import create_app
from lumina_core.models.router import set_router
from tests.support.mock_router import MockModelRouter

BOOK_ID = "b1"
SEG_ID = "s1"

REQUIRED_BOOK_COLUMNS = frozenset({"is_favorite", "category", "last_opened_at"})
REQUIRED_SEGMENT_COLUMNS = frozenset(
    {
        "chapter",
        "page_range",
        "summary_json",
        "label",
        "translation",
        "char_count",
        "summary_provider",
        "summary_model",
        "summary_duration_s",
        "summary_llm_attempts",
    }
)


def _create_legacy_db(db_path: Path) -> None:
    """Simulate a pre-library-upgrade Lumina database."""
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
        CREATE TABLE notes (
          id TEXT PRIMARY KEY,
          book_id TEXT NOT NULL,
          segment_id TEXT,
          content TEXT NOT NULL,
          type TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE jobs (
          id TEXT PRIMARY KEY,
          book_id TEXT,
          kind TEXT,
          status TEXT,
          created_at TEXT,
          updated_at TEXT
        );
        CREATE TABLE chat_sessions (
          id TEXT PRIMARY KEY,
          book_id TEXT,
          scope TEXT,
          updated_at TEXT
        );
        CREATE TABLE chat_messages (
          id TEXT PRIMARY KEY,
          session_id TEXT,
          role TEXT,
          content TEXT,
          created_at TEXT
        );
        CREATE VIRTUAL TABLE search_fts USING fts5(
          book_id UNINDEXED,
          segment_id UNINDEXED,
          note_id UNINDEXED,
          kind UNINDEXED,
          title,
          body,
          tokenize='trigram'
        );
        INSERT INTO books VALUES (
          'b1', 'Legacy Book', NULL, 'txt', '/tmp/legacy.txt',
          1, 'reading', 'hash1', '{}',
          '2024-01-01T00:00:00+00:00', '2024-01-01T00:00:00+00:00'
        );
        INSERT INTO segments VALUES (
          's1', 'b1', 0, '开篇', '段 1', 'hello world', 'ready', 0
        );
        """
    )
    conn.commit()
    conn.close()


@pytest.fixture
def legacy_upgraded_client(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMINA_DATA_DIR", str(tmp_path))
    db_path = tmp_path / "lumina.db"
    _create_legacy_db(db_path)

    # Prove legacy schema breaks list queries before migration.
    raw = sqlite3.connect(db_path)
    raw.row_factory = sqlite3.Row
    with pytest.raises(sqlite3.OperationalError, match="last_opened_at"):
        BookRepo(raw).list_books(sort="recent")
    raw.close()

    init_db(db_path)

    router = MockModelRouter(responses={"summarize": {"category": "文学"}})
    app = create_app(Settings(data_dir=tmp_path))
    app.state.lumina.router = router
    app.state.lumina.job_queue.router = router
    set_router(router)
    with TestClient(app) as client:
        yield client


def test_legacy_schema_migrates_required_columns(tmp_path):
    db_path = tmp_path / "legacy.db"
    _create_legacy_db(db_path)
    conn = init_db(db_path)

    book_cols = {row[1] for row in conn.execute("PRAGMA table_info(books)")}
    seg_cols = {row[1] for row in conn.execute("PRAGMA table_info(segments)")}
    note_cols = {row[1] for row in conn.execute("PRAGMA table_info(notes)")}

    assert REQUIRED_BOOK_COLUMNS <= book_cols
    assert REQUIRED_SEGMENT_COLUMNS <= seg_cols
    assert "quote" in note_cols
    conn.close()


def test_legacy_db_library_apis_return_200(legacy_upgraded_client):
    client = legacy_upgraded_client

    assert client.get("/books", params={"sort": "recent"}).status_code == 200
    assert client.get("/books", params={"sort": "favorite"}).status_code == 200

    book = client.get(f"/books/{BOOK_ID}")
    assert book.status_code == 200
    assert book.json()["title"] == "Legacy Book"

    segments = client.get(f"/books/{BOOK_ID}/segments")
    assert segments.status_code == 200
    body = segments.json()["segments"]
    assert len(body) == 1
    assert body[0]["idx"] == 0
    assert "raw_text" not in body[0]
    assert "char_count" in body[0]

    opened = client.post(f"/books/{BOOK_ID}/open")
    assert opened.status_code == 200
    assert opened.json()["status"] == "opened"


def test_legacy_db_list_books_after_migration(tmp_path):
    db_path = tmp_path / "legacy.db"
    _create_legacy_db(db_path)
    conn = init_db(db_path)
    repo = BookRepo(conn)

    recent = repo.list_books(sort="recent")
    assert len(recent) == 1
    assert recent[0]["id"] == BOOK_ID

    favorites = repo.list_books(sort="favorite")
    assert len(favorites) == 1
    conn.close()
