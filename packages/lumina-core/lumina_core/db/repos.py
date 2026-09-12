"""Data access layer."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from lumina_core.chunker.markers import lumina_chapter_label
from lumina_core.chunker.tree import (
    decode_heading_path,
    encode_heading_path,
    heading_path_from_chapter,
)
from lumina_core.classify.book import BOOK_CATEGORIES
from lumina_core.db.connection import db_lock, db_transaction
from lumina_core.search.fts import delete_note_from_fts
from lumina_core.summarize.preview import segment_list_fields
from lumina_core.summarize.schema import normalize_summary_data, resolve_segment_label


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


ORPHAN_INGEST_ERROR = "导入中断"


TITLE_USER_SET_KEY = "title_user_set"


def _parse_metadata(book: dict[str, Any]) -> dict[str, Any]:
    raw = book.get("metadata_json")
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def metadata_with_title_user_set(book: dict[str, Any]) -> dict[str, Any]:
    meta = _parse_metadata(book)
    meta[TITLE_USER_SET_KEY] = True
    return meta


def resolve_ingest_title(
    book: dict[str, Any] | None,
    extracted_title: str,
    metadata: dict[str, Any],
) -> str:
    """Keep a user-edited display title when ingest finalizes the book."""
    if not book or not _parse_metadata(book).get(TITLE_USER_SET_KEY):
        return extracted_title
    metadata[TITLE_USER_SET_KEY] = True
    current = str(book.get("title") or "").strip()
    return current or extracted_title


# SQL-level filters. `summarizing` / `idle` / `segmenting` are applied after
# JobQueue state is attached (see routes.apply_book_list_filter).
_SQL_FILTERS = frozenset(
    {
        "all",
        "summarized",
        "error",
        "unread",
        "reading",
        "finished",
        "favorite",
        *BOOK_CATEGORIES,
    }
)
_QUEUE_FILTERS = frozenset({"summarizing", "idle", "segmenting"})
BOOK_FILTERS = _SQL_FILTERS | _QUEUE_FILTERS
BOOK_SORTS = frozenset({"recent", "added", "title", "favorite", "segments", "progress"})

# Reading-progress percent: unread / single-segment → 0; last segment → 1;
# otherwise index / segment_count. Matches client ReadingProgress.percent.
_PROGRESS_SORT_SQL = (
    "CASE"
    " WHEN last_opened_at IS NULL THEN 0.0"
    " WHEN COALESCE(segment_count, 0) <= 1 THEN 0.0"
    " WHEN COALESCE(current_segment_index, 0) >= (segment_count - 1) THEN 1.0"
    " ELSE CAST(MAX(COALESCE(current_segment_index, 0), 0) AS REAL)"
    "  / segment_count"
    " END DESC, title COLLATE NOCASE ASC"
)

_SORT_ORDER: dict[str, str] = {
    "recent": "last_opened_at IS NULL, last_opened_at DESC, updated_at DESC",
    "added": "created_at DESC",
    "title": "title COLLATE NOCASE ASC",
    "favorite": "is_favorite DESC, last_opened_at IS NULL, last_opened_at DESC, updated_at DESC",
    "segments": "COALESCE(segment_count, 0) DESC, title COLLATE NOCASE ASC",
    "progress": _PROGRESS_SORT_SQL,
}

# Reading progress is derived from last_opened_at + segment index — not books.status
# (status becomes "summarized" when summaries finish and would hide 在读).
_READING_FILTER_SQL: dict[str, str] = {
    "unread": "last_opened_at IS NULL",
    "finished": (
        "last_opened_at IS NOT NULL AND COALESCE(segment_count, 0) > 1 "
        "AND COALESCE(current_segment_index, 0) >= (segment_count - 1)"
    ),
    "reading": (
        "last_opened_at IS NOT NULL AND ("
        "COALESCE(segment_count, 0) <= 1 OR "
        "COALESCE(current_segment_index, 0) < (segment_count - 1))"
    ),
}


def reading_progress_bucket(book: dict[str, Any]) -> str:
    """Return unread | reading | finished from open + segment progress.

    Single-segment books stay 'reading' after open: the only index is also
    the last index, so they cannot be distinguished from 已读完 without a
    separate flag.
    """
    if not book.get("last_opened_at"):
        return "unread"
    segment_count = int(book.get("segment_count") or 0)
    if segment_count <= 1:
        return "reading"
    index = int(book.get("current_segment_index") or 0)
    if index >= segment_count - 1:
        return "finished"
    return "reading"


class BookRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def find_by_hash(self, file_hash: str) -> dict[str, Any] | None:
        with db_lock(self.conn):
            row = self.conn.execute(
                "SELECT * FROM books WHERE file_hash = ?", (file_hash,)
            ).fetchone()
        return dict(row) if row else None

    def get(self, book_id: str) -> dict[str, Any] | None:
        with db_lock(self.conn):
            row = self.conn.execute(
                "SELECT * FROM books WHERE id = ?", (book_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_books(
        self,
        *,
        filter: str = "all",
        sort: str = "recent",
    ) -> list[dict[str, Any]]:
        if filter not in BOOK_FILTERS:
            filter = "all"
        if sort not in BOOK_SORTS:
            sort = "recent"
        order = _SORT_ORDER[sort]
        sql = "SELECT * FROM books"
        params: tuple[Any, ...] = ()
        sql_filter = filter if filter in _SQL_FILTERS else "all"
        if sql_filter == "summarized":
            sql += " WHERE status = 'summarized'"
        elif sql_filter == "error":
            sql += " WHERE status = 'error'"
        elif sql_filter == "favorite":
            sql += " WHERE is_favorite = 1"
        elif sql_filter in _READING_FILTER_SQL:
            sql += f" WHERE {_READING_FILTER_SQL[sql_filter]}"
        elif sql_filter in BOOK_CATEGORIES:
            sql += " WHERE category = ?"
            params = (sql_filter,)
        sql += f" ORDER BY {order}"
        with db_lock(self.conn):
            rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def insert(self, **fields: Any) -> dict[str, Any]:
        book_id = fields.get("id") or str(uuid.uuid4())
        now = _now()
        with db_transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO books (
                  id, title, author, format, file_path, language, target_language,
                  segment_count, status, file_hash, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    book_id,
                    fields["title"],
                    fields.get("author"),
                    fields["format"],
                    fields["file_path"],
                    fields.get("language"),
                    fields.get("target_language"),
                    fields.get("segment_count", 0),
                    fields.get("status", "unread"),
                    fields.get("file_hash"),
                    json.dumps(fields.get("metadata_json") or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return self.get(book_id)  # type: ignore[return-value]

    def update(self, book_id: str, **fields: Any) -> None:
        fields["updated_at"] = _now()
        if "metadata_json" in fields and isinstance(fields["metadata_json"], dict):
            fields["metadata_json"] = json.dumps(fields["metadata_json"], ensure_ascii=False)
        cols = ", ".join(f"{k} = ?" for k in fields)
        with db_transaction(self.conn):
            self.conn.execute(
                f"UPDATE books SET {cols} WHERE id = ?",
                (*fields.values(), book_id),
            )

    def repair_stale_imports(
        self,
        live_ids: set[str] | frozenset[str] | None = None,
        *,
        restore_orphaned_resegment: bool = False,
    ) -> int:
        """Move abandoned 0-segment imports into 导入失败.

        List-path skips `status=processing` so a concurrent GET /books cannot
        race an in-flight insert. Pass live ingest/resegment ids as extra
        protection. 0-segment unread rows are not 未摘要 or 已摘要.

        At process start, `restore_orphaned_resegment` marks abandoned
        0-segment processing as 导入失败, and turns processing books that
        already have segments back to unread (crashed resegment).
        """
        live_ids = live_ids or set()
        repaired = 0
        for book in self.list_books():
            book_id = book["id"]
            if book_id in live_ids:
                continue
            status = book.get("status")
            if status == "error":
                continue
            # List-path must not touch processing: ingest registers the
            # live id after insert, and a concurrent GET /books could
            # otherwise mark an in-flight import as 导入失败.
            # Startup (restore_orphaned_resegment) owns abandoned processing.
            if status == "processing" and not restore_orphaned_resegment:
                continue
            total = int(book.get("segment_count") or 0)
            if total <= 0:
                meta = _parse_metadata(book)
                if not (
                    isinstance(meta.get("ingest_error"), str)
                    and meta["ingest_error"].strip()
                ):
                    meta["ingest_error"] = ORPHAN_INGEST_ERROR
                self.update(book_id, status="error", metadata_json=meta)
                repaired += 1
            elif restore_orphaned_resegment and status == "processing":
                self.update(book_id, status="unread")
                repaired += 1
        return repaired

    def drop_stored_document_trees(self) -> int:
        """Strip unused ingest trees in SQLite so Python never json.loads megabytes.

        sqlite3 releases the GIL around the C update, so /health can run while
        a leftover tree is removed from an already-imported huge book.
        """
        try:
            with db_transaction(self.conn):
                cursor = self.conn.execute(
                    """
                    UPDATE books
                    SET metadata_json = json_remove(metadata_json, '$.document_tree'),
                        updated_at = ?
                    WHERE json_type(metadata_json, '$.document_tree') IS NOT NULL
                    """,
                    (_now(),),
                )
            return int(cursor.rowcount or 0)
        except sqlite3.OperationalError:
            return self._drop_stored_document_trees_python()

    def _drop_stored_document_trees_python(self) -> int:
        stripped = 0
        for book in self.list_books():
            time.sleep(0.001)
            meta = _parse_metadata(book)
            if "document_tree" not in meta:
                continue
            meta.pop("document_tree")
            self.update(book["id"], metadata_json=meta)
            stripped += 1
        return stripped

    def claim_processing(self, book_id: str) -> bool:
        """Atomically transition a non-processing book into processing."""
        with db_transaction(self.conn):
            cursor = self.conn.execute(
                """
                UPDATE books
                SET status = 'processing', updated_at = ?
                WHERE id = ? AND status != 'processing'
                """,
                (_now(), book_id),
            )
        return cursor.rowcount == 1

    def delete(self, book_id: str) -> None:
        with db_transaction(self.conn):
            self.conn.execute("DELETE FROM notes WHERE book_id = ?", (book_id,))
            self.conn.execute(
                """
                DELETE FROM chat_messages
                WHERE session_id IN (
                    SELECT id FROM chat_sessions WHERE book_id = ?
                )
                """,
                (book_id,),
            )
            self.conn.execute("DELETE FROM chat_sessions WHERE book_id = ?", (book_id,))
            self.conn.execute("DELETE FROM summary_nodes WHERE book_id = ?", (book_id,))
            self.conn.execute("DELETE FROM segments WHERE book_id = ?", (book_id,))
            self.conn.execute("DELETE FROM jobs WHERE book_id = ?", (book_id,))
            self.conn.execute("DELETE FROM search_fts WHERE book_id = ?", (book_id,))
            self.conn.execute("DELETE FROM books WHERE id = ?", (book_id,))

    def maybe_mark_summarized(self, book_id: str) -> bool:
        """If every segment is ready, promote book status to summarized."""
        with db_lock(self.conn):
            row = self.conn.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN summary_status = 'ready' THEN 1 ELSE 0 END) AS ready
                FROM segments WHERE book_id = ?
                """,
                (book_id,),
            ).fetchone()
        if not row or row["total"] == 0 or row["ready"] != row["total"]:
            return False
        self.update(book_id, status="summarized", summarize_intent="idle")
        return True

    def summary_progress(self, book_id: str) -> dict[str, int]:
        """Return ready/total segment counts for summary progress UI."""
        with db_lock(self.conn):
            row = self.conn.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN summary_status = 'ready' THEN 1 ELSE 0 END) AS ready
                FROM segments WHERE book_id = ?
                """,
                (book_id,),
            ).fetchone()
        if not row:
            return {"summary_ready_count": 0, "summary_total_count": 0}
        return {
            "summary_ready_count": int(row["ready"] or 0),
            "summary_total_count": int(row["total"] or 0),
        }


# List API / UI sidebar: slim meta — no raw_text, translation, or summary_json.
_SEGMENT_LIST_COLUMNS = (
    "id, book_id, idx, chapter, heading_path, page_range, anchor_label, char_count, "
    "label, summary_status, retry_count, "
    "summary_provider, summary_model, summary_tier, summary_duration_s, summary_llm_attempts, "
    "summary_preview, bullet_labels"
)

# Optional include_summary=1 on list API (export/debug).
_SEGMENT_META_COLUMNS = (
    f"{_SEGMENT_LIST_COLUMNS}, summary_json"
)

_SEGMENT_SUMMARY_COLUMNS = (
    "idx, summary_json, label, anchor_label, summary_status, "
    "summary_provider, summary_model, summary_tier, summary_duration_s, summary_llm_attempts"
)

# Export: summary + translation without loading raw_text.
_SEGMENT_EXPORT_COLUMNS = (
    "id, book_id, idx, chapter, page_range, anchor_label, char_count, "
    "summary_json, label, summary_status, retry_count, "
    "summary_provider, summary_model, summary_tier, summary_duration_s, summary_llm_attempts, translation"
)
_SEGMENT_INSERT_BATCH = 200
_SEGMENT_INSERT_SQL = """
INSERT INTO segments (
  id, book_id, idx, chapter, heading_path, page_range, anchor_label,
  raw_text, char_count, summary_status, retry_count
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _heading_path_db_value(seg: dict[str, Any]) -> str | None:
    raw = seg.get("heading_path")
    if isinstance(raw, str) and raw.strip().startswith("["):
        return raw
    if isinstance(raw, (list, tuple)):
        encoded = encode_heading_path(raw)
        if encoded:
            return encoded
    return encode_heading_path(heading_path_from_chapter(seg.get("chapter")))


def _segment_insert_row(seg: dict[str, Any]) -> tuple[Any, ...]:
    return (
        seg["id"],
        seg["book_id"],
        seg["idx"],
        lumina_chapter_label(seg.get("chapter")),
        _heading_path_db_value(seg),
        seg.get("page_range"),
        seg.get("anchor_label"),
        seg["raw_text"],
        seg.get("char_count", len(seg.get("raw_text") or "")),
        seg.get("summary_status", "pending"),
        seg.get("retry_count", 0),
    )


def _decode_bullet_labels(raw: Any) -> list[str] | None:
    """DB may store JSON text; clients expect a string array (or null)."""
    if raw is None:
        return None
    if isinstance(raw, list):
        labels = [str(x).strip() for x in raw if str(x).strip()]
        return labels or None
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, list):
            labels = [str(x).strip() for x in parsed if str(x).strip()]
            return labels or None
    return None


def _segment_public(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    if "chapter" in item:
        item["chapter"] = lumina_chapter_label(item.get("chapter"))
    if "heading_path" in item or "chapter" in item:
        item["heading_path"] = decode_heading_path(
            item.get("heading_path"), chapter=item.get("chapter")
        )
    # SELECT * may include legacy TEXT cache columns; never emit a JSON string
    # for bullet_labels — Swift/Windows SegmentRow decode as [String]?.
    if "bullet_labels" in item:
        item["bullet_labels"] = _decode_bullet_labels(item.get("bullet_labels"))
    return item


def _insert_segments_batched(conn: sqlite3.Connection, segments: list[dict[str, Any]]) -> None:
    """Commit inserts in chunks so a huge book does not hold one WAL write for minutes."""
    for offset in range(0, len(segments), _SEGMENT_INSERT_BATCH):
        batch = segments[offset : offset + _SEGMENT_INSERT_BATCH]
        with db_transaction(conn):
            conn.executemany(
                _SEGMENT_INSERT_SQL,
                [_segment_insert_row(seg) for seg in batch],
            )
        time.sleep(0.001)


class SegmentRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def list_for_book(
        self,
        book_id: str,
        *,
        include_body: bool = True,
        include_summary: bool = False,
    ) -> list[dict[str, Any]]:
        if include_body:
            cols = "*"
        elif include_summary:
            cols = _SEGMENT_META_COLUMNS
        else:
            cols = _SEGMENT_LIST_COLUMNS
        with db_lock(self.conn):
            rows = self.conn.execute(
                f"SELECT {cols} FROM segments WHERE book_id = ? ORDER BY idx",
                (book_id,),
            ).fetchall()
        return [_segment_public(r) for r in rows]

    def list_catalog(self, book_id: str) -> list[dict[str, Any]]:
        """Slim cached catalog. The open-book hot path never parses summary_json."""
        with db_lock(self.conn):
            rows = self.conn.execute(
                f"SELECT {_SEGMENT_LIST_COLUMNS} FROM segments "
                "WHERE book_id = ? ORDER BY idx",
                (book_id,),
            ).fetchall()
        catalog: list[dict[str, Any]] = []
        for row in rows:
            item = _segment_public(row)
            if item.get("summary_status") != "ready":
                item.pop("summary_preview", None)
                item.pop("bullet_labels", None)
            elif not item.get("summary_preview"):
                item.pop("summary_preview", None)
            if not item.get("bullet_labels"):
                item.pop("bullet_labels", None)
            catalog.append(item)
        return catalog

    def backfill_catalog_cache(self, *, batch_size: int = 64) -> int:
        """Populate legacy ready rows in bounded transactions.

        This runs from a worker thread during startup recovery. Parsing happens
        outside the shared connection lock, and each write transaction is small.
        """
        updated = 0
        while True:
            with db_lock(self.conn):
                rows = self.conn.execute(
                    """
                    SELECT id, summary_json
                    FROM segments
                    WHERE summary_status = 'ready'
                      AND summary_json IS NOT NULL
                      AND (summary_preview IS NULL OR bullet_labels IS NULL)
                    ORDER BY book_id, idx
                    LIMIT ?
                    """,
                    (batch_size,),
                ).fetchall()
            if not rows:
                return updated
            values: list[tuple[str, str, str]] = []
            for row in rows:
                preview, labels = segment_list_fields(row["summary_json"])
                values.append(
                    (
                        preview or "",
                        json.dumps(labels, ensure_ascii=False),
                        row["id"],
                    )
                )
            with db_transaction(self.conn):
                self.conn.executemany(
                    """
                    UPDATE segments
                    SET summary_preview = ?, bullet_labels = ?
                    WHERE id = ?
                    """,
                    values,
                )
            updated += len(values)
            time.sleep(0.001)

    def backfill_prefix_labels(self, *, batch_size: int = 64) -> int:
        """Fill empty labels from the first summary sentence head.

        Only touches ready rows with a blank label. Existing labels (including
        short sentence heads) are left alone. Runs from a worker thread during
        startup recovery.
        """
        updated = 0
        after_id = ""
        while True:
            with db_lock(self.conn):
                rows = self.conn.execute(
                    """
                    SELECT id, label, summary_json, anchor_label
                    FROM segments
                    WHERE summary_status = 'ready'
                      AND summary_json IS NOT NULL
                      AND (label IS NULL OR TRIM(label) = '')
                      AND id > ?
                    ORDER BY id
                    LIMIT ?
                    """,
                    (after_id, batch_size),
                ).fetchall()
            if not rows:
                return updated
            values: list[tuple[str, str]] = []
            for row in rows:
                after_id = row["id"]
                raw = row["summary_json"]
                try:
                    parsed = json.loads(raw) if isinstance(raw, str) else raw
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(parsed, dict):
                    continue
                normalized = normalize_summary_data(parsed)
                new_label = resolve_segment_label(
                    None,
                    sentences=normalized.get("sentences"),
                    fallback_anchor=row["anchor_label"] or "要点",
                )
                if new_label:
                    values.append((new_label, row["id"]))
            if values:
                with db_transaction(self.conn):
                    self.conn.executemany(
                        "UPDATE segments SET label = ? WHERE id = ?",
                        values,
                    )
                updated += len(values)
            time.sleep(0.001)

    def list_for_export(self, book_id: str) -> list[dict[str, Any]]:
        with db_lock(self.conn):
            rows = self.conn.execute(
                f"SELECT {_SEGMENT_EXPORT_COLUMNS} FROM segments WHERE book_id = ? ORDER BY idx",
                (book_id,),
            ).fetchall()
        return [_segment_public(r) for r in rows]

    def backfill_char_counts(self, book_id: str) -> None:
        with db_lock(self.conn):
            row = self.conn.execute(
                """
                SELECT 1 FROM segments
                WHERE book_id = ?
                  AND raw_text IS NOT NULL
                  AND (char_count IS NULL OR char_count = 0)
                LIMIT 1
                """,
                (book_id,),
            ).fetchone()
        if not row:
            return
        with db_transaction(self.conn):
            self.conn.execute(
                """
                UPDATE segments
                SET char_count = LENGTH(raw_text)
                WHERE book_id = ?
                  AND raw_text IS NOT NULL
                  AND (char_count IS NULL OR char_count = 0)
                """,
                (book_id,),
            )

    def get(self, segment_id: str) -> dict[str, Any] | None:
        with db_lock(self.conn):
            row = self.conn.execute(
                "SELECT * FROM segments WHERE id = ?", (segment_id,)
            ).fetchone()
        return _segment_public(row) if row else None

    def get_by_index(self, book_id: str, idx: int) -> dict[str, Any] | None:
        with db_lock(self.conn):
            row = self.conn.execute(
                "SELECT * FROM segments WHERE book_id = ? AND idx = ?",
                (book_id, idx),
            ).fetchone()
        return _segment_public(row) if row else None

    def get_summary_by_index(self, book_id: str, idx: int) -> dict[str, Any] | None:
        with db_lock(self.conn):
            row = self.conn.execute(
                f"SELECT {_SEGMENT_SUMMARY_COLUMNS} FROM segments WHERE book_id = ? AND idx = ?",
                (book_id, idx),
            ).fetchone()
        return _segment_public(row) if row else None

    def summary_tier_for_book(self, book_id: str) -> str:
        with db_lock(self.conn):
            row = self.conn.execute(
                """
                SELECT summary_tier FROM segments
                WHERE book_id = ? AND summary_json IS NOT NULL
                ORDER BY idx LIMIT 1
                """,
                (book_id,),
            ).fetchone()
        if row and row["summary_tier"] == "advanced":
            return "advanced"
        return "normal"

    def list_ready_summaries_before(
        self,
        book_id: str,
        idx: int,
        *,
        limit: int = 32,
    ) -> list[dict[str, Any]]:
        """Return recent summary-only rows before idx, newest first."""
        with db_lock(self.conn):
            rows = self.conn.execute(
                """
                SELECT idx, chapter, summary_json
                FROM segments
                WHERE book_id = ?
                  AND idx < ?
                  AND summary_status = 'ready'
                  AND summary_json IS NOT NULL
                  AND summary_json != ''
                ORDER BY idx DESC
                LIMIT ?
                """,
                (book_id, idx, max(1, limit)),
            ).fetchall()
        return [
            {
                "idx": row["idx"],
                "chapter": lumina_chapter_label(row["chapter"]),
                "summary_json": row["summary_json"],
            }
            for row in rows
        ]

    def list_ready_summaries(self, book_id: str) -> list[dict[str, Any]]:
        """Ready segment summaries in reading order, without raw_text."""
        with db_lock(self.conn):
            rows = self.conn.execute(
                """
                SELECT id, idx, chapter, label, summary_json
                FROM segments
                WHERE book_id = ?
                  AND summary_status = 'ready'
                  AND summary_json IS NOT NULL
                  AND summary_json != ''
                ORDER BY idx
                """,
                (book_id,),
            ).fetchall()
        return [_segment_public(row) for row in rows]

    def get_bodies_by_indices(
        self,
        book_id: str,
        indices: list[int],
    ) -> dict[int, dict[str, Any]]:
        """Load selected segments (including raw_text) by idx. Empty indices → {}."""
        if not indices:
            return {}
        unique = sorted({int(i) for i in indices})
        placeholders = ",".join("?" * len(unique))
        with db_lock(self.conn):
            rows = self.conn.execute(
                f"""
                SELECT id, idx, label, summary_json, raw_text, chapter
                FROM segments
                WHERE book_id = ? AND idx IN ({placeholders})
                """,
                (book_id, *unique),
            ).fetchall()
        return {int(row["idx"]): _segment_public(row) for row in rows}

    def insert_many(self, segments: list[dict[str, Any]]) -> None:
        if not segments:
            return
        with db_transaction(self.conn):
            self.conn.executemany(
                _SEGMENT_INSERT_SQL,
                [_segment_insert_row(seg) for seg in segments],
            )

    def finalize_ingest(
        self,
        book_id: str,
        segments: list[dict[str, Any]],
        *,
        title: str,
        author: str | None,
        language: str | None,
        target_language: str,
        metadata_json: dict[str, Any],
    ) -> None:
        """Insert segments in batches, then mark the book unread.

        Readers must never see status=unread with an empty segment list.
        The book stays `processing` until every batch and the final UPDATE commit.
        """
        if not segments:
            raise RuntimeError("分段结果为空")
        now = _now()
        _insert_segments_batched(self.conn, segments)
        with db_transaction(self.conn):
            self.conn.execute(
                """
                UPDATE books
                SET title = ?, author = ?, language = ?, target_language = ?,
                    segment_count = ?, status = 'unread', metadata_json = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    title,
                    author,
                    language,
                    target_language,
                    len(segments),
                    json.dumps(metadata_json, ensure_ascii=False),
                    now,
                    book_id,
                ),
            )

    def complete_ingest(
        self,
        book_id: str,
        *,
        title: str,
        author: str | None,
        language: str | None,
        target_language: str,
        metadata_json: dict[str, Any],
        segment_count: int,
    ) -> None:
        """Mark a book unread after streamed segment inserts."""
        if segment_count <= 0:
            raise RuntimeError("分段结果为空")
        now = _now()
        with db_transaction(self.conn):
            self.conn.execute(
                """
                UPDATE books
                SET title = ?, author = ?, language = ?, target_language = ?,
                    segment_count = ?, status = 'unread', metadata_json = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    title,
                    author,
                    language,
                    target_language,
                    segment_count,
                    json.dumps(metadata_json, ensure_ascii=False),
                    now,
                    book_id,
                ),
            )

    def begin_segment_staging(self) -> None:
        self.conn.execute("DROP TABLE IF EXISTS temp.staging_segments")
        self.conn.execute(
            """
            CREATE TEMP TABLE staging_segments (
              id TEXT,
              book_id TEXT,
              idx INTEGER,
              chapter TEXT,
              heading_path TEXT,
              page_range TEXT,
              anchor_label TEXT,
              raw_text TEXT,
              char_count INTEGER,
              summary_status TEXT,
              retry_count INTEGER
            )
            """
        )

    def insert_staging(self, segments: list[dict[str, Any]]) -> None:
        if not segments:
            return
        with db_transaction(self.conn):
            self.conn.executemany(
                """
                INSERT INTO staging_segments (
                  id, book_id, idx, chapter, heading_path, page_range, anchor_label,
                  raw_text, char_count, summary_status, retry_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [_segment_insert_row(seg) for seg in segments],
            )
        time.sleep(0.001)

    def commit_staging_replace(
        self,
        book_id: str,
        *,
        metadata_json: dict[str, Any],
        status: str,
        segment_count: int,
    ) -> None:
        if segment_count <= 0:
            raise RuntimeError("分段结果为空")
        now = _now()
        with db_transaction(self.conn):
            self.conn.execute("DELETE FROM notes WHERE book_id = ?", (book_id,))
            self.conn.execute(
                """
                DELETE FROM chat_messages
                WHERE session_id IN (
                    SELECT id FROM chat_sessions WHERE book_id = ?
                )
                """,
                (book_id,),
            )
            self.conn.execute("DELETE FROM chat_sessions WHERE book_id = ?", (book_id,))
            self.conn.execute("DELETE FROM jobs WHERE book_id = ?", (book_id,))
            self.conn.execute("DELETE FROM summary_nodes WHERE book_id = ?", (book_id,))
            self.conn.execute(
                "DELETE FROM search_fts WHERE book_id = ? AND kind != 'book'",
                (book_id,),
            )
            self.conn.execute("DELETE FROM segments WHERE book_id = ?", (book_id,))
            self.conn.execute(
                """
                INSERT INTO segments (
                  id, book_id, idx, chapter, heading_path, page_range, anchor_label,
                  raw_text, char_count, summary_status, retry_count
                )
                SELECT
                  id, book_id, idx, chapter, heading_path, page_range, anchor_label,
                  raw_text, char_count, summary_status, retry_count
                FROM staging_segments
                ORDER BY idx
                """
            )
            self.conn.execute(
                """
                UPDATE books
                SET segment_count = ?, current_segment_index = 0, status = ?,
                    metadata_json = ?, index_status = 'idle', updated_at = ?
                WHERE id = ?
                """,
                (
                    segment_count,
                    status,
                    json.dumps(metadata_json, ensure_ascii=False),
                    now,
                    book_id,
                ),
            )
        self.conn.execute("DROP TABLE IF EXISTS temp.staging_segments")

    def replace_for_book(
        self,
        book_id: str,
        segments: list[dict[str, Any]],
        *,
        metadata_json: dict[str, Any],
        status: str,
    ) -> None:
        """Atomically replace segment-bound data after a successful rechunk."""
        now = _now()
        with db_transaction(self.conn):
            self.conn.execute("DELETE FROM notes WHERE book_id = ?", (book_id,))
            self.conn.execute(
                """
                DELETE FROM chat_messages
                WHERE session_id IN (
                    SELECT id FROM chat_sessions WHERE book_id = ?
                )
                """,
                (book_id,),
            )
            self.conn.execute("DELETE FROM chat_sessions WHERE book_id = ?", (book_id,))
            self.conn.execute("DELETE FROM jobs WHERE book_id = ?", (book_id,))
            self.conn.execute("DELETE FROM summary_nodes WHERE book_id = ?", (book_id,))
            self.conn.execute(
                "DELETE FROM search_fts WHERE book_id = ? AND kind != 'book'",
                (book_id,),
            )
            self.conn.execute("DELETE FROM segments WHERE book_id = ?", (book_id,))
        _insert_segments_batched(self.conn, segments)
        with db_transaction(self.conn):
            self.conn.execute(
                """
                UPDATE books
                SET segment_count = ?, current_segment_index = 0, status = ?,
                    metadata_json = ?, index_status = 'idle', updated_at = ?
                WHERE id = ?
                """,
                (
                    len(segments),
                    status,
                    json.dumps(metadata_json, ensure_ascii=False),
                    now,
                    book_id,
                ),
            )

    def update_summary(
        self,
        segment_id: str,
        *,
        summary_json: str,
        label: str,
        anchor_label: str | None = None,
        status: str = "ready",
        summary_provider: str | None = None,
        summary_model: str | None = None,
        summary_tier: str = "normal",
        summary_duration_s: float | None = None,
        summary_llm_attempts: int | None = None,
    ) -> None:
        summary_preview, bullet_labels = segment_list_fields(summary_json)
        try:
            parsed = json.loads(summary_json) if isinstance(summary_json, str) else summary_json
        except (json.JSONDecodeError, TypeError):
            parsed = None
        stored_label = label
        if isinstance(parsed, dict):
            normalized = normalize_summary_data(parsed)
            stored_label = resolve_segment_label(
                label,
                sentences=normalized.get("sentences"),
                fallback_anchor=anchor_label or label or "要点",
            )
        with db_transaction(self.conn):
            self.conn.execute(
                """
                UPDATE segments SET summary_json = ?, label = ?, anchor_label = COALESCE(?, anchor_label),
                summary_status = ?, retry_count = 0,
                summary_provider = ?, summary_model = ?, summary_tier = ?,
                summary_duration_s = ?, summary_llm_attempts = ?,
                summary_preview = ?, bullet_labels = ?
                WHERE id = ?
                """,
                (
                    summary_json,
                    stored_label,
                    anchor_label,
                    status,
                    summary_provider,
                    summary_model,
                    summary_tier,
                    summary_duration_s,
                    summary_llm_attempts,
                    summary_preview or "",
                    json.dumps(bullet_labels, ensure_ascii=False),
                    segment_id,
                ),
            )

    def reset_summary(self, segment_id: str, *, summary_tier: str) -> None:
        """Invalidate one summary while retaining source text and segment identity."""
        with db_transaction(self.conn):
            self.conn.execute(
                """
                UPDATE segments
                SET summary_json = NULL, label = NULL, translation = NULL,
                    summary_status = 'pending', retry_count = 0,
                    summary_provider = NULL, summary_model = NULL,
                    summary_tier = ?, summary_duration_s = NULL,
                    summary_llm_attempts = NULL, summary_preview = NULL,
                    bullet_labels = NULL
                WHERE id = ?
                """,
                (summary_tier, segment_id),
            )

    def apply_boundary_move(
        self,
        left: dict[str, Any],
        right: dict[str, Any],
        *,
        left_text: str,
        right_text: str,
        left_chapter: str | None,
        right_chapter: str | None,
        left_page_range: str | None,
        right_page_range: str | None,
        left_anchor: str,
        right_anchor: str,
        summary_tier: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Rewrite adjacent segment text, remap notes by quote, and reset summaries."""
        from lumina_core.chunker.boundary import remap_note_segment_id

        left_id = left["id"]
        right_id = right["id"]
        with db_transaction(self.conn):
            notes = self.conn.execute(
                """
                SELECT id, segment_id, quote FROM notes
                WHERE segment_id IN (?, ?)
                """,
                (left_id, right_id),
            ).fetchall()
            for note in notes:
                next_id = remap_note_segment_id(
                    note["quote"],
                    note["segment_id"],
                    left_id,
                    right_id,
                    left_text,
                    right_text,
                )
                if next_id != note["segment_id"]:
                    self.conn.execute(
                        "UPDATE notes SET segment_id = ? WHERE id = ?",
                        (next_id, note["id"]),
                    )
            self._write_boundary_side(
                left,
                raw_text=left_text,
                chapter=left_chapter,
                page_range=left_page_range,
                anchor_label=left_anchor,
                summary_tier=summary_tier,
            )
            self._write_boundary_side(
                right,
                raw_text=right_text,
                chapter=right_chapter,
                page_range=right_page_range,
                anchor_label=right_anchor,
                summary_tier=summary_tier,
            )
        updated_left = self.get(left_id)
        updated_right = self.get(right_id)
        if updated_left is None or updated_right is None:
            raise RuntimeError("Boundary move lost a segment")
        return updated_left, updated_right

    def _write_boundary_side(
        self,
        segment: dict[str, Any],
        *,
        raw_text: str,
        chapter: str | None,
        page_range: str | None,
        anchor_label: str,
        summary_tier: str,
    ) -> None:
        self.conn.execute(
            """
            UPDATE segments
            SET raw_text = ?, char_count = ?, chapter = ?, heading_path = ?, page_range = ?,
                anchor_label = ?, summary_json = NULL, label = NULL,
                translation = NULL, summary_status = 'pending', retry_count = 0,
                summary_provider = NULL, summary_model = NULL, summary_tier = ?,
                summary_duration_s = NULL, summary_llm_attempts = NULL,
                summary_preview = NULL, bullet_labels = NULL
            WHERE id = ?
            """,
            (
                raw_text,
                len(raw_text),
                lumina_chapter_label(chapter),
                encode_heading_path(heading_path_from_chapter(chapter)),
                page_range,
                anchor_label,
                summary_tier,
                segment["id"],
            ),
        )

    def set_status(self, segment_id: str, status: str, retry_count: int | None = None) -> None:
        with db_transaction(self.conn):
            if retry_count is None:
                self.conn.execute(
                    "UPDATE segments SET summary_status = ? WHERE id = ?",
                    (status, segment_id),
                )
            else:
                self.conn.execute(
                    "UPDATE segments SET summary_status = ?, retry_count = ? WHERE id = ?",
                    (status, retry_count, segment_id),
                )


class SummaryNodeRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def delete_for_book(self, book_id: str) -> None:
        with db_transaction(self.conn):
            self.conn.execute("DELETE FROM summary_nodes WHERE book_id = ?", (book_id,))

    def replace_for_book(self, book_id: str, nodes: list[dict[str, Any]]) -> None:
        with db_transaction(self.conn):
            self.conn.execute("DELETE FROM summary_nodes WHERE book_id = ?", (book_id,))
            if not nodes:
                return
            self.conn.executemany(
                """
                INSERT INTO summary_nodes (
                  id, book_id, level, parent_id, sort_idx, segment_id,
                  segment_idx_start, segment_idx_end, chapter, label, summary_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        n["id"],
                        book_id,
                        int(n["level"]),
                        n.get("parent_id"),
                        int(n["sort_idx"]),
                        n.get("segment_id"),
                        n.get("segment_idx_start"),
                        n.get("segment_idx_end"),
                        n.get("chapter"),
                        n.get("label"),
                        n.get("summary_json"),
                        n.get("status", "ready"),
                    )
                    for n in nodes
                ],
            )

    def list_for_book(self, book_id: str) -> list[dict[str, Any]]:
        with db_lock(self.conn):
            rows = self.conn.execute(
                """
                SELECT * FROM summary_nodes
                WHERE book_id = ?
                ORDER BY level, sort_idx
                """,
                (book_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_root(self, book_id: str) -> dict[str, Any] | None:
        with db_lock(self.conn):
            row = self.conn.execute(
                """
                SELECT * FROM summary_nodes
                WHERE book_id = ? AND level = 0
                ORDER BY sort_idx
                LIMIT 1
                """,
                (book_id,),
            ).fetchone()
        return dict(row) if row else None


class ChatRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get_or_create_session(self, book_id: str) -> dict[str, Any]:
        with db_lock(self.conn):
            row = self.conn.execute(
                "SELECT * FROM chat_sessions WHERE book_id = ? ORDER BY updated_at DESC LIMIT 1",
                (book_id,),
            ).fetchone()
        if row:
            return dict(row)
        session_id = str(uuid.uuid4())
        now = _now()
        with db_transaction(self.conn):
            self.conn.execute(
                "INSERT INTO chat_sessions (id, book_id, scope, updated_at) VALUES (?, ?, ?, ?)",
                (session_id, book_id, "book", now),
            )
        return {"id": session_id, "book_id": book_id, "scope": "book", "updated_at": now}

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        citations_json: str | None = None,
        web_refs_json: str | None = None,
    ) -> dict[str, Any]:
        msg_id = str(uuid.uuid4())
        now = _now()
        with db_transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO chat_messages (id, session_id, role, content, citations_json, web_refs_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (msg_id, session_id, role, content, citations_json, web_refs_json, now),
            )
            self.conn.execute(
                "UPDATE chat_sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
        return {
            "id": msg_id,
            "session_id": session_id,
            "role": role,
            "content": content,
            "citations_json": citations_json,
            "web_refs_json": web_refs_json,
            "created_at": now,
        }

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        with db_lock(self.conn):
            rows = self.conn.execute(
                "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at",
                (session_id,),
            ).fetchall()
        return [dict(r) for r in rows]


_NOTE_LIST_SQL = """
SELECT
  n.id, n.book_id, n.segment_id, n.quote, n.content, n.type, n.created_at,
  s.idx AS segment_index,
  COALESCE(NULLIF(s.label, ''), s.anchor_label, '段 ' || (s.idx + 1)) AS segment_label,
  b.title AS book_title
FROM notes n
JOIN segments s ON s.id = n.segment_id
JOIN books b ON b.id = n.book_id
"""


class NoteRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create(
        self,
        *,
        book_id: str,
        content: str,
        segment_id: str,
        note_type: str = "manual",
        quote: str | None = None,
    ) -> dict[str, Any]:
        note_id = str(uuid.uuid4())
        now = _now()
        with db_transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO notes (id, book_id, segment_id, quote, content, type, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (note_id, book_id, segment_id, quote, content, note_type, now),
            )
        enriched = self._list(where="n.id = ?", params=(note_id,))
        return enriched[0]

    def list_for_book(
        self, book_id: str, *, segment_id: str | None = None
    ) -> list[dict[str, Any]]:
        if segment_id:
            return self._list(
                where="n.book_id = ? AND n.segment_id = ?",
                params=(book_id, segment_id),
            )
        return self._list(where="n.book_id = ?", params=(book_id,))

    def list_all(self) -> list[dict[str, Any]]:
        return self._list(where="1=1", params=())

    def get(self, note_id: str) -> dict[str, Any] | None:
        rows = self._list(where="n.id = ?", params=(note_id,))
        return rows[0] if rows else None

    def delete(self, note_id: str) -> bool:
        with db_transaction(self.conn):
            cur = self.conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            if cur.rowcount == 0:
                return False
            delete_note_from_fts(self.conn, note_id)
        return True

    def _list(self, *, where: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with db_lock(self.conn):
            rows = self.conn.execute(
                f"{_NOTE_LIST_SQL} WHERE {where} ORDER BY n.created_at DESC",
                params,
            ).fetchall()
        return [dict(r) for r in rows]


class NewsChatRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def list_messages(self, article_id: str) -> list[dict[str, Any]]:
        with db_lock(self.conn):
            rows = self.conn.execute(
                "SELECT * FROM news_chat_messages WHERE article_id = ? ORDER BY created_at",
                (article_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def add_message(
        self,
        article_id: str,
        role: str,
        content: str,
        *,
        web_refs_json: str | None = None,
    ) -> dict[str, Any]:
        msg_id = str(uuid.uuid4())
        now = _now()
        with db_transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO news_chat_messages (id, article_id, role, content, web_refs_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (msg_id, article_id, role, content, web_refs_json, now),
            )
        return {
            "id": msg_id,
            "article_id": article_id,
            "role": role,
            "content": content,
            "web_refs_json": web_refs_json,
            "created_at": now,
        }
