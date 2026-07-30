"""SQLite schema and initialization."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from lumina_core.db.connection import attach_db_lock

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS books (
  id            TEXT PRIMARY KEY,
  title         TEXT NOT NULL,
  author        TEXT,
  format        TEXT NOT NULL,
  file_path     TEXT NOT NULL,
  cover_path    TEXT,
  language      TEXT,
  target_language TEXT,
  translation_mode TEXT DEFAULT 'auto',
  segment_count INTEGER DEFAULT 0,
  current_segment_index INTEGER DEFAULT 0,
  status        TEXT DEFAULT 'unread',
  file_hash     TEXT,
  metadata_json TEXT,
  is_favorite   INTEGER DEFAULT 0,
  category      TEXT,
  last_opened_at TEXT,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS segments (
  id              TEXT PRIMARY KEY,
  book_id         TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  idx             INTEGER NOT NULL,
  chapter         TEXT,
  page_range      TEXT,
  anchor_label    TEXT,
  raw_text        TEXT,
  summary_json    TEXT,
  label           TEXT,
  translation     TEXT,
  summary_status  TEXT DEFAULT 'pending',
  retry_count     INTEGER DEFAULT 0,
  summary_provider TEXT,
  summary_model    TEXT,
  summary_duration_s REAL,
  summary_llm_attempts INTEGER,
  UNIQUE(book_id, idx)
);

CREATE TABLE IF NOT EXISTS notes (
  id          TEXT PRIMARY KEY,
  book_id     TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  segment_id  TEXT NOT NULL REFERENCES segments(id),
  quote       TEXT,
  content     TEXT NOT NULL,
  type        TEXT NOT NULL,
  created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_sessions (
  id          TEXT PRIMARY KEY,
  book_id     TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  scope       TEXT DEFAULT 'book',
  segment_id  TEXT,
  updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
  id          TEXT PRIMARY KEY,
  session_id  TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
  role        TEXT NOT NULL,
  content     TEXT NOT NULL,
  citations_json TEXT,
  web_refs_json  TEXT,
  created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
  id          TEXT PRIMARY KEY,
  book_id     TEXT,
  kind        TEXT NOT NULL,
  payload_json TEXT,
  status      TEXT DEFAULT 'pending',
  priority    INTEGER DEFAULT 0,
  retry_count INTEGER DEFAULT 0,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
  book_id UNINDEXED, segment_id UNINDEXED, note_id UNINDEXED, kind UNINDEXED, title, body,
  tokenize='trigram'
);

CREATE TABLE IF NOT EXISTS news_sources (
  id          TEXT PRIMARY KEY,
  url         TEXT NOT NULL UNIQUE,
  title       TEXT,
  created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS news_articles (
  id            TEXT PRIMARY KEY,
  source_id     TEXT NOT NULL,
  url           TEXT NOT NULL UNIQUE,
  title         TEXT NOT NULL,
  excerpt       TEXT,
  author        TEXT,
  published_at  TEXT,
  synced_at     TEXT NOT NULL,
  rss_summary   TEXT,
  one_liner     TEXT,
  score_hint    REAL,
  fetched_text_path TEXT,
  summary_markdown TEXT,
  summary_status TEXT DEFAULT 'idle'
);

CREATE TABLE IF NOT EXISTS news_chat_messages (
  id            TEXT PRIMARY KEY,
  article_id    TEXT NOT NULL REFERENCES news_articles(id) ON DELETE CASCADE,
  role          TEXT NOT NULL,
  content       TEXT NOT NULL,
  web_refs_json TEXT,
  created_at    TEXT NOT NULL
);
"""


_NEWS_ARTICLE_COLUMNS = (
    ("rss_summary", "TEXT"),
    ("one_liner", "TEXT"),
    ("score_hint", "REAL"),
    ("fetched_text_path", "TEXT"),
    ("summary_markdown", "TEXT"),
    ("summary_status", "TEXT DEFAULT 'idle'"),
)


_BOOK_COLUMNS = (
    ("is_favorite", "INTEGER DEFAULT 0"),
    ("category", "TEXT"),
    ("last_opened_at", "TEXT"),
)

_SEGMENT_COLUMNS = (
    ("chapter", "TEXT"),
    ("page_range", "TEXT"),
    ("summary_json", "TEXT"),
    ("label", "TEXT"),
    ("translation", "TEXT"),
    ("summary_provider", "TEXT"),
    ("summary_model", "TEXT"),
    ("char_count", "INTEGER"),
    ("summary_duration_s", "REAL"),
    ("summary_llm_attempts", "INTEGER"),
)

_NOTE_COLUMNS = (("quote", "TEXT"),)


def _migrate_books(conn: sqlite3.Connection) -> None:
    info = conn.execute("PRAGMA table_info(books)").fetchall()
    if not info:
        return
    existing = {row[1] for row in info}
    for name, col_type in _BOOK_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE books ADD COLUMN {name} {col_type}")
    if "status" in existing:
        conn.execute("UPDATE books SET status = 'unread' WHERE status = 'processing'")


def _migrate_segments(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(segments)").fetchall()}
    for name, col_type in _SEGMENT_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE segments ADD COLUMN {name} {col_type}")


def _migrate_news_articles(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(news_articles)").fetchall()}
    for name, col_type in _NEWS_ARTICLE_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE news_articles ADD COLUMN {name} {col_type}")


def _migrate_notes_columns(conn: sqlite3.Connection) -> None:
    info = conn.execute("PRAGMA table_info(notes)").fetchall()
    if not info:
        return
    existing = {row[1] for row in info}
    for name, col_type in _NOTE_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE notes ADD COLUMN {name} {col_type}")


def _migrate_notes_require_segment(conn: sqlite3.Connection) -> None:
    """Drop orphan notes and enforce segment_id NOT NULL on existing DBs."""
    _migrate_notes_columns(conn)
    info = conn.execute("PRAGMA table_info(notes)").fetchall()
    if not info:
        return
    seg_col = next((row for row in info if row[1] == "segment_id"), None)
    if seg_col is None:
        return
    # PRAGMA table_info: cid, name, type, notnull, dflt_value, pk
    if seg_col[3] == 1:
        return

    orphans = conn.execute("SELECT id FROM notes WHERE segment_id IS NULL").fetchall()
    for row in orphans:
        conn.execute("DELETE FROM search_fts WHERE note_id = ?", (row[0],))
    conn.execute("DELETE FROM notes WHERE segment_id IS NULL")

    conn.execute(
        """
        CREATE TABLE notes_migrated (
          id          TEXT PRIMARY KEY,
          book_id     TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
          segment_id  TEXT NOT NULL REFERENCES segments(id),
          quote       TEXT,
          content     TEXT NOT NULL,
          type        TEXT NOT NULL,
          created_at  TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO notes_migrated (id, book_id, segment_id, quote, content, type, created_at)
        SELECT id, book_id, segment_id, quote, content, type, created_at FROM notes
        """
    )
    conn.execute("DROP TABLE notes")
    conn.execute("ALTER TABLE notes_migrated RENAME TO notes")


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA_SQL)
    _migrate_news_articles(conn)
    _migrate_books(conn)
    _migrate_segments(conn)
    _migrate_notes_require_segment(conn)
    conn.commit()
    attach_db_lock(conn)
    return conn
