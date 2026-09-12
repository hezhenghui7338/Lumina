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
  summary_ready_count INTEGER DEFAULT 0,
  summary_total_count INTEGER DEFAULT 0,
  current_segment_index INTEGER DEFAULT 0,
  status        TEXT DEFAULT 'unread',
  file_hash     TEXT,
  metadata_json TEXT,
  is_favorite   INTEGER DEFAULT 0,
  category      TEXT,
  last_opened_at TEXT,
  index_status  TEXT DEFAULT 'idle',
  summarize_intent TEXT DEFAULT 'idle',
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS segments (
  id              TEXT PRIMARY KEY,
  book_id         TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  idx             INTEGER NOT NULL,
  chapter         TEXT,
  heading_path    TEXT,
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
  summary_tier     TEXT DEFAULT 'normal',
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

CREATE TABLE IF NOT EXISTS summary_nodes (
  id                 TEXT PRIMARY KEY,
  book_id            TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  level              INTEGER NOT NULL,
  parent_id          TEXT,
  sort_idx           INTEGER NOT NULL,
  segment_id         TEXT,
  segment_idx_start  INTEGER,
  segment_idx_end    INTEGER,
  chapter            TEXT,
  label              TEXT,
  summary_json       TEXT,
  status             TEXT DEFAULT 'pending',
  UNIQUE(book_id, level, sort_idx)
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

-- Maps entity ids to FTS rowids so DELETE never scans UNINDEXED columns.
CREATE TABLE IF NOT EXISTS search_fts_map (
  doc_key   TEXT PRIMARY KEY,
  book_id   TEXT NOT NULL,
  kind      TEXT NOT NULL,
  fts_rowid INTEGER NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_search_fts_map_book ON search_fts_map(book_id);

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


# Columns added after the original books table. CREATE TABLE IF NOT EXISTS does
# not alter an existing table, so every SCHEMA_SQL books column that older DBs
# may lack must appear here — including sort keys like current_segment_index.
_BOOK_COLUMNS = (
    # Core columns some ultra-legacy DBs lack (notes-era fixtures omit these).
    ("segment_count", "INTEGER DEFAULT 0"),
    ("status", "TEXT DEFAULT 'unread'"),
    ("file_hash", "TEXT"),
    ("metadata_json", "TEXT"),
    ("cover_path", "TEXT"),
    ("language", "TEXT"),
    ("target_language", "TEXT"),
    ("translation_mode", "TEXT DEFAULT 'auto'"),
    ("current_segment_index", "INTEGER DEFAULT 0"),
    ("is_favorite", "INTEGER DEFAULT 0"),
    ("category", "TEXT"),
    ("last_opened_at", "TEXT"),
    ("index_status", "TEXT DEFAULT 'idle'"),
    ("summarize_intent", "TEXT DEFAULT 'idle'"),
    # Denormalized summary progress — maintained on segment write paths so
    # GET /books never N+1 COUNT(segments) per book.
    ("summary_ready_count", "INTEGER DEFAULT 0"),
    ("summary_total_count", "INTEGER DEFAULT 0"),
)

_SEGMENT_COLUMNS = (
    ("chapter", "TEXT"),
    ("heading_path", "TEXT"),
    ("page_range", "TEXT"),
    ("summary_json", "TEXT"),
    ("label", "TEXT"),
    ("translation", "TEXT"),
    ("summary_provider", "TEXT"),
    ("summary_model", "TEXT"),
    ("summary_tier", "TEXT DEFAULT 'normal'"),
    ("char_count", "INTEGER"),
    ("summary_duration_s", "REAL"),
    ("summary_llm_attempts", "INTEGER"),
    # Optional catalog cache; always decoded to a JSON array (never raw TEXT) in API.
    ("summary_preview", "TEXT"),
    ("bullet_labels", "TEXT"),
)

_NOTE_COLUMNS = (("quote", "TEXT"),)


def _backfill_summary_progress(conn: sqlite3.Connection) -> None:
    """One-shot: copy segment ready/total into books after adding the columns."""
    info = {row[1] for row in conn.execute("PRAGMA table_info(books)").fetchall()}
    if "summary_ready_count" not in info or "summary_total_count" not in info:
        return
    conn.execute(
        """
        UPDATE books
        SET summary_total_count = (
              SELECT COUNT(*) FROM segments WHERE segments.book_id = books.id
            ),
            summary_ready_count = (
              SELECT COUNT(*) FROM segments
              WHERE segments.book_id = books.id
                AND segments.summary_status = 'ready'
            )
        """
    )
    # Keep segment_count aligned when it drifted (legacy rows). Skip when the
    # column is still missing — ultra-legacy DBs get it via _BOOK_COLUMNS first.
    if "segment_count" not in info:
        return
    if "status" in info:
        conn.execute(
            """
            UPDATE books
            SET segment_count = summary_total_count
            WHERE COALESCE(segment_count, 0) != COALESCE(summary_total_count, 0)
              AND status != 'processing'
            """
        )
    else:
        conn.execute(
            """
            UPDATE books
            SET segment_count = summary_total_count
            WHERE COALESCE(segment_count, 0) != COALESCE(summary_total_count, 0)
            """
        )


def _migrate_books(conn: sqlite3.Connection) -> None:
    info = conn.execute("PRAGMA table_info(books)").fetchall()
    if not info:
        return
    existing = {row[1] for row in info}
    added_progress = False
    for name, col_type in _BOOK_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE books ADD COLUMN {name} {col_type}")
            if name in ("summary_ready_count", "summary_total_count"):
                added_progress = True
    if added_progress:
        _backfill_summary_progress(conn)
    # Never flip status=processing → unread here. That left 0-segment books
    # outside 分段中 / 未摘要 / 导入失败. Orphans are repaired in
    # BookRepo.repair_stale_imports.


def _migrate_segments(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(segments)").fetchall()}
    added_tier = False
    for name, col_type in _SEGMENT_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE segments ADD COLUMN {name} {col_type}")
            if name == "summary_tier":
                added_tier = True
    # Full-table UPDATE on segments scans every raw_text blob. On a multi-GB
    # library that is 10–20s *every cold start* even when 0 rows match.
    # Only backfill when we just added the column; readers already treat NULL
    # as "normal" via `or "normal"` / COALESCE.
    if added_tier:
        conn.execute(
            "UPDATE segments SET summary_tier = 'normal' "
            "WHERE summary_tier IS NULL OR summary_tier = ''"
        )


def _migrate_news_articles(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(news_articles)").fetchall()}
    for name, col_type in _NEWS_ARTICLE_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE news_articles ADD COLUMN {name} {col_type}")


def _migrate_summary_nodes(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS summary_nodes (
          id                 TEXT PRIMARY KEY,
          book_id            TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
          level              INTEGER NOT NULL,
          parent_id          TEXT,
          sort_idx           INTEGER NOT NULL,
          segment_id         TEXT,
          segment_idx_start  INTEGER,
          segment_idx_end    INTEGER,
          chapter            TEXT,
          label              TEXT,
          summary_json       TEXT,
          status             TEXT DEFAULT 'pending',
          UNIQUE(book_id, level, sort_idx)
        )
        """
    )


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
        from lumina_core.search.fts import delete_note_from_fts

        delete_note_from_fts(conn, row[0])
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


def migrate_search_fts_map(conn: sqlite3.Connection) -> None:
    """Ensure search_fts_map exists and backfill from FTS content (idempotent)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS search_fts_map (
          doc_key   TEXT PRIMARY KEY,
          book_id   TEXT NOT NULL,
          kind      TEXT NOT NULL,
          fts_rowid INTEGER NOT NULL UNIQUE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_search_fts_map_book ON search_fts_map(book_id)"
    )
    map_count = conn.execute("SELECT COUNT(*) AS c FROM search_fts_map").fetchone()[0]
    if map_count:
        return
    try:
        fts_count = conn.execute("SELECT COUNT(*) AS c FROM search_fts").fetchone()[0]
    except sqlite3.OperationalError:
        return
    if not fts_count:
        return

    rows = conn.execute(
        "SELECT rowid, book_id, segment_id, note_id, kind FROM search_fts"
    ).fetchall()
    best: dict[str, tuple[int, str, str]] = {}
    stale_rowids: list[int] = []
    for row in rows:
        rowid = int(row[0])
        book_id = row[1] or ""
        segment_id = row[2]
        note_id = row[3]
        kind = (row[4] or "").strip() or "segment"
        if kind == "book":
            entity_id = book_id
        elif kind == "note":
            entity_id = note_id or ""
        else:
            kind = "segment"
            entity_id = segment_id or ""
        if not entity_id or not book_id:
            stale_rowids.append(rowid)
            continue
        doc_key = f"{kind}:{entity_id}"
        prev = best.get(doc_key)
        if prev is None:
            best[doc_key] = (rowid, book_id, kind)
        elif rowid >= prev[0]:
            stale_rowids.append(prev[0])
            best[doc_key] = (rowid, book_id, kind)
        else:
            stale_rowids.append(rowid)

    for rowid in stale_rowids:
        conn.execute("DELETE FROM search_fts WHERE rowid = ?", (rowid,))
    for doc_key, (rowid, book_id, kind) in best.items():
        conn.execute(
            """
            INSERT OR REPLACE INTO search_fts_map (doc_key, book_id, kind, fts_rowid)
            VALUES (?, ?, ?, ?)
            """,
            (doc_key, book_id, kind, rowid),
        )


def connect_db(db_path: Path) -> sqlite3.Connection:
    """Open an existing database with the runtime concurrency settings."""
    from lumina_core.perf import instrument_connection

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    wrapped = instrument_connection(conn)
    attach_db_lock(wrapped)
    wrapped.execute("PRAGMA journal_mode=WAL")
    wrapped.execute("PRAGMA busy_timeout=5000")
    return wrapped  # type: ignore[return-value]


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect_db(db_path)
    conn.executescript(SCHEMA_SQL)
    _migrate_news_articles(conn)
    _migrate_books(conn)
    _migrate_segments(conn)
    _migrate_summary_nodes(conn)
    migrate_search_fts_map(conn)
    _migrate_notes_require_segment(conn)
    conn.commit()
    return conn
