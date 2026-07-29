"""Notes require segment_id; list enrichment."""

from __future__ import annotations

import sqlite3

import pytest

from lumina_core.db.repos import BookRepo, NoteRepo
from lumina_core.db.schema import init_db
from lumina_core.search.fts import index_note


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "notes.db")


def _seed_book_with_segment(conn: sqlite3.Connection) -> tuple[str, str]:
    conn.execute(
        """
        INSERT INTO books (id, title, author, format, file_path, created_at, updated_at)
        VALUES ('b1', '测试书', NULL, 'txt', '/x', 'now', 'now')
        """
    )
    conn.execute(
        """
        INSERT INTO segments (id, book_id, idx, label, anchor_label, raw_text, summary_status)
        VALUES ('s1', 'b1', 0, '开篇', '段 1', '正文', 'ready')
        """
    )
    conn.commit()
    return "b1", "s1"


def test_note_create_and_list_enrichment(conn):
    book_id, segment_id = _seed_book_with_segment(conn)
    repo = NoteRepo(conn)
    note = repo.create(
        book_id=book_id,
        content="要点",
        segment_id=segment_id,
        note_type="manual",
    )
    assert note["segment_id"] == segment_id
    assert note["segment_index"] == 0
    assert note["segment_label"] == "开篇"
    assert note["book_title"] == "测试书"

    listed = repo.list_for_book(book_id)
    assert len(listed) == 1
    assert listed[0]["book_title"] == "测试书"

    filtered = repo.list_for_book(book_id, segment_id=segment_id)
    assert len(filtered) == 1

    all_notes = repo.list_all()
    assert len(all_notes) == 1


def test_note_delete_removes_row_and_fts(conn):
    book_id, segment_id = _seed_book_with_segment(conn)
    repo = NoteRepo(conn)
    note = repo.create(
        book_id=book_id,
        content="待删笔记",
        segment_id=segment_id,
        note_type="manual",
    )
    book = BookRepo(conn).get(book_id)
    assert book is not None
    index_note(conn, book, note)

    fts_before = conn.execute(
        "SELECT note_id FROM search_fts WHERE note_id = ?", (note["id"],)
    ).fetchall()
    assert len(fts_before) == 1

    assert repo.delete(note["id"]) is True
    assert repo.get(note["id"]) is None
    assert repo.list_all() == []

    fts_rows = conn.execute(
        "SELECT note_id FROM search_fts WHERE note_id = ?", (note["id"],)
    ).fetchall()
    assert fts_rows == []


def test_note_delete_not_found(conn):
    repo = NoteRepo(conn)
    assert repo.delete("missing-note-id") is False


def test_migrate_drops_orphan_notes(tmp_path):
    db = tmp_path / "legacy.db"
    raw = sqlite3.connect(str(db))
    raw.executescript(
        """
        CREATE TABLE books (
          id TEXT PRIMARY KEY, title TEXT NOT NULL, author TEXT, format TEXT NOT NULL,
          file_path TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE segments (
          id TEXT PRIMARY KEY, book_id TEXT NOT NULL, idx INTEGER NOT NULL,
          label TEXT, anchor_label TEXT, raw_text TEXT, summary_status TEXT
        );
        CREATE TABLE notes (
          id TEXT PRIMARY KEY, book_id TEXT NOT NULL,
          segment_id TEXT, quote TEXT, content TEXT NOT NULL,
          type TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE search_fts USING fts5(
          book_id UNINDEXED, segment_id UNINDEXED, note_id UNINDEXED, kind UNINDEXED, title, body,
          tokenize='trigram'
        );
        INSERT INTO books VALUES ('b1', '书', NULL, 'txt', '/x', 'now', 'now');
        INSERT INTO segments (id, book_id, idx, raw_text) VALUES ('s1', 'b1', 0, 't');
        INSERT INTO notes VALUES ('orphan', 'b1', NULL, NULL, '游离', 'manual', 'now');
        INSERT INTO notes VALUES ('ok', 'b1', 's1', NULL, '挂段', 'manual', 'now');
        INSERT INTO search_fts (book_id, segment_id, note_id, kind, title, body)
          VALUES ('b1', NULL, 'orphan', 'note', 't', '游离');
        """
    )
    raw.commit()
    raw.close()

    conn = init_db(db)
    rows = conn.execute("SELECT id FROM notes ORDER BY id").fetchall()
    assert [r[0] for r in rows] == ["ok"]
    info = {r[1]: r[3] for r in conn.execute("PRAGMA table_info(notes)").fetchall()}
    assert info["segment_id"] == 1
