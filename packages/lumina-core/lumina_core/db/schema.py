"""SQLite schema and initialization."""

from __future__ import annotations

import sqlite3
from pathlib import Path

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
  UNIQUE(book_id, idx)
);

CREATE TABLE IF NOT EXISTS notes (
  id          TEXT PRIMARY KEY,
  book_id     TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  segment_id  TEXT REFERENCES segments(id),
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
  synced_at     TEXT NOT NULL
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


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn
