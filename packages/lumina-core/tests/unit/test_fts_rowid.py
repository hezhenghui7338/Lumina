"""FTS updates must use rowid via search_fts_map (never UNINDEXED column DELETE)."""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from lumina_core.config import Settings
from lumina_core.db.schema import init_db, migrate_search_fts_map
from lumina_core.main import create_app
from lumina_core.search.fts import (
    delete_book_from_fts,
    delete_book_segments_from_fts,
    index_book,
    index_segment,
    search,
)


def _seed_book(conn: sqlite3.Connection, *, n_segments: int = 3) -> tuple[dict, list[dict]]:
    book_id = str(uuid.uuid4())
    book = {"id": book_id, "title": "性能测试书", "author": "作者"}
    conn.execute(
        """
        INSERT INTO books (id, title, author, format, file_path, segment_count, created_at, updated_at)
        VALUES (?, ?, ?, 'txt', '/x', ?, 'now', 'now')
        """,
        (book_id, book["title"], book["author"], n_segments),
    )
    segs: list[dict] = []
    body = ("汉字测试正文内容" * 200)[:4000]
    for i in range(n_segments):
        seg_id = str(uuid.uuid4())
        seg = {
            "id": seg_id,
            "book_id": book_id,
            "idx": i,
            "label": f"段{i}",
            "summary_json": '{"sentences":["要点"]}',
            "raw_text": body,
            "translation": None,
        }
        conn.execute(
            """
            INSERT INTO segments (id, book_id, idx, label, raw_text, summary_json, summary_status)
            VALUES (?, ?, ?, ?, ?, ?, 'ready')
            """,
            (seg_id, book_id, i, seg["label"], body, seg["summary_json"]),
        )
        segs.append(seg)
    conn.commit()
    return book, segs


def test_index_segment_twice_no_duplicates(tmp_path):
    conn = init_db(tmp_path / "fts.db")
    book, segs = _seed_book(conn, n_segments=1)
    index_book(conn, book)
    index_segment(conn, book, segs[0])
    index_segment(conn, book, {**segs[0], "label": "更新后"})
    rows = conn.execute(
        "SELECT COUNT(*) AS c FROM search_fts WHERE segment_id = ?",
        (segs[0]["id"],),
    ).fetchone()
    assert rows[0] == 1
    map_row = conn.execute(
        "SELECT kind FROM search_fts_map WHERE doc_key = ?",
        (f"segment:{segs[0]['id']}",),
    ).fetchone()
    assert map_row is not None
    # Trigram needs ≥3 chars; body seed includes 「汉字测试正文内容」.
    hits = search(conn, "汉字测试正文")
    assert sum(1 for h in hits if h.get("segment_id") == segs[0]["id"]) == 1


def test_index_segment_uses_rowid_delete_not_unindexed(tmp_path, monkeypatch):
    from lumina_core.search import fts as fts_module

    conn = init_db(tmp_path / "fts2.db")
    book, segs = _seed_book(conn, n_segments=40)
    index_book(conn, book)
    for seg in segs:
        index_segment(conn, book, seg)

    rowid_deletes: list[int] = []
    orig_delete = fts_module._delete_by_rowid

    def spy_delete(c, rowid: int) -> None:
        rowid_deletes.append(int(rowid))
        return orig_delete(c, rowid)

    monkeypatch.setattr(fts_module, "_delete_by_rowid", spy_delete)

    t0 = time.perf_counter()
    index_segment(conn, book, {**segs[0], "label": "再更新"})
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert rowid_deletes, "expected a rowid delete on re-index"
    assert elapsed_ms < 500, elapsed_ms


def test_migrate_search_fts_map_backfills_existing_fts(tmp_path):
    db = tmp_path / "legacy.db"
    raw = sqlite3.connect(str(db))
    raw.executescript(
        """
        CREATE VIRTUAL TABLE search_fts USING fts5(
          book_id UNINDEXED, segment_id UNINDEXED, note_id UNINDEXED, kind UNINDEXED,
          title, body, tokenize='trigram'
        );
        INSERT INTO search_fts (book_id, segment_id, note_id, kind, title, body)
        VALUES ('b1', 's1', NULL, 'segment', 't', '正文可搜');
        INSERT INTO search_fts (book_id, segment_id, note_id, kind, title, body)
        VALUES ('b1', NULL, NULL, 'book', '书名', '作者');
        """
    )
    raw.commit()
    raw.close()

    conn = init_db(db)
    map_count = conn.execute("SELECT COUNT(*) AS c FROM search_fts_map").fetchone()[0]
    assert map_count == 2
    hits = search(conn, "正文可搜")
    assert any(h.get("segment_id") == "s1" for h in hits)


def test_delete_book_segments_keeps_book_row(tmp_path):
    conn = init_db(tmp_path / "del.db")
    book, segs = _seed_book(conn, n_segments=5)
    index_book(conn, book)
    for seg in segs:
        index_segment(conn, book, seg)
    delete_book_segments_from_fts(conn, book["id"])
    kinds = [
        r[0]
        for r in conn.execute(
            "SELECT kind FROM search_fts WHERE book_id = ?", (book["id"],)
        ).fetchall()
    ]
    assert kinds == ["book"]
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM search_fts_map WHERE book_id = ? AND kind = 'segment'",
            (book["id"],),
        ).fetchone()[0]
        == 0
    )


def test_delete_book_from_fts_clears_all(tmp_path):
    conn = init_db(tmp_path / "del2.db")
    book, segs = _seed_book(conn, n_segments=3)
    index_book(conn, book)
    for seg in segs:
        index_segment(conn, book, seg)
    delete_book_from_fts(conn, book["id"])
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM search_fts WHERE book_id = ?", (book["id"],)
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM search_fts_map WHERE book_id = ?", (book["id"],)
        ).fetchone()[0]
        == 0
    )


def test_books_list_stays_responsive_during_segment_reindex(tmp_path):
    """Re-indexing many segments must not pin GET /books for multi-second stalls."""
    settings = Settings(data_dir=tmp_path)
    app = create_app(settings)
    client = TestClient(app)
    conn = app.state.lumina.conn
    book, segs = _seed_book(conn, n_segments=80)
    index_book(conn, book)
    for seg in segs:
        index_segment(conn, book, seg)

    stop = threading.Event()
    errors: list[BaseException] = []
    max_books_ms = {"v": 0.0}

    def reindex_loop() -> None:
        try:
            i = 0
            while not stop.is_set():
                seg = segs[i % len(segs)]
                index_segment(conn, book, {**seg, "label": f"l{i}"})
                i += 1
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    worker = threading.Thread(target=reindex_loop, daemon=True)
    worker.start()
    time.sleep(0.05)
    try:
        for _ in range(12):
            t0 = time.perf_counter()
            resp = client.get("/books")
            elapsed_ms = (time.perf_counter() - t0) * 1000
            max_books_ms["v"] = max(max_books_ms["v"], elapsed_ms)
            assert resp.status_code == 200
            time.sleep(0.02)
    finally:
        stop.set()
        worker.join(timeout=5)

    assert errors == []
    # Rowid deletes should keep list latency well under the old 10s+ cliff.
    assert max_books_ms["v"] < 2000, max_books_ms["v"]


def test_migrate_is_idempotent(tmp_path):
    conn = init_db(tmp_path / "idem.db")
    book, segs = _seed_book(conn, n_segments=2)
    index_segment(conn, book, segs[0])
    before = conn.execute("SELECT COUNT(*) FROM search_fts_map").fetchone()[0]
    migrate_search_fts_map(conn)
    after = conn.execute("SELECT COUNT(*) FROM search_fts_map").fetchone()[0]
    assert before == after
