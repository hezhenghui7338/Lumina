"""Shared SQLite connection must serialize cross-thread access."""

from __future__ import annotations

import threading
import time
import uuid

from lumina_core.db.repos import BookRepo, SegmentRepo
from lumina_core.db.schema import connect_db, init_db
from lumina_core.jobs.ingest import _persist_ingest_sync


def test_concurrent_get_during_persist_ingest(tmp_path):
    """Regression: unlocked reads raced ingest to_thread writes → InterfaceError."""
    db_path = tmp_path / "lock.db"
    conn = init_db(db_path)
    book_id = str(uuid.uuid4())
    books = BookRepo(conn)
    books.insert(
        id=book_id,
        title="t",
        format="txt",
        file_path="/x",
        status="processing",
    )

    segments = [
        {
            "id": str(uuid.uuid4()),
            "book_id": book_id,
            "idx": i,
            "chapter": None,
            "page_range": None,
            "anchor_label": f"a{i}",
            "raw_text": ("hello world " * 50),
            "summary_status": "pending",
            "retry_count": 0,
        }
        for i in range(80)
    ]

    errors: list[BaseException] = []
    stop = threading.Event()

    def reader() -> None:
        repo = BookRepo(conn)
        while not stop.is_set():
            try:
                repo.get(book_id)
                repo.summary_progress(book_id)
            except BaseException as exc:  # noqa: BLE001 — collect for assert
                errors.append(exc)
                return

    workers = [threading.Thread(target=reader) for _ in range(4)]
    for w in workers:
        w.start()

    time.sleep(0.02)
    try:
        _persist_ingest_sync(
            db_path,
            book_id=book_id,
            src=tmp_path / "sample.txt",
            metadata={},
            detected_language="zh",
            target_language="zh-CN",
            segments=segments,
            ingest_meta={"total_char_count": 100, "chunker_version": "test"},
        )
    finally:
        stop.set()
        for w in workers:
            w.join(timeout=2)

    assert not errors, f"concurrent SQLite access failed: {errors[0]!r}"
    assert books.get(book_id)["status"] == "unread"
    assert len(SegmentRepo(conn).list_for_book(book_id, include_body=False)) == 80
    conn.close()


def _ingest_segment(book_id: str, idx: int) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "book_id": book_id,
        "idx": idx,
        "chapter": None,
        "page_range": None,
        "anchor_label": f"a{idx}",
        "raw_text": f"段落 {idx}。" + ("正文 " * 40),
        "summary_status": "pending",
        "retry_count": 0,
    }


def test_persist_ingest_never_exposes_unread_without_segments(tmp_path):
    """status=unread must not be visible before segment rows exist."""
    db_path = tmp_path / "unread-race.db"
    api_conn = init_db(db_path)
    book_id = str(uuid.uuid4())
    BookRepo(api_conn).insert(
        id=book_id,
        title="t",
        format="txt",
        file_path="/x",
        status="processing",
    )
    segments = [_ingest_segment(book_id, i) for i in range(120)]
    bad: list[tuple[str | None, int, int]] = []
    stop = threading.Event()

    def reader() -> None:
        books = BookRepo(api_conn)
        segs = SegmentRepo(api_conn)
        while not stop.is_set():
            book = books.get(book_id)
            listed = segs.list_for_book(book_id, include_body=False)
            if book and book.get("status") != "processing" and not listed:
                bad.append(
                    (book.get("status"), int(book.get("segment_count") or 0), len(listed))
                )
                return

    worker = threading.Thread(target=reader)
    worker.start()
    time.sleep(0.01)
    try:
        _persist_ingest_sync(
            db_path,
            book_id=book_id,
            src=tmp_path / "sample.txt",
            metadata={},
            detected_language="zh",
            target_language="zh-CN",
            segments=segments,
            ingest_meta={"total_char_count": 100, "chunker_version": "test"},
        )
    finally:
        stop.set()
        worker.join(timeout=2)

    assert not bad, f"unread before segments: {bad[0]!r}"
    book = BookRepo(api_conn).get(book_id)
    assert book["status"] == "unread"
    assert len(SegmentRepo(api_conn).list_for_book(book_id, include_body=False)) == 120
    api_conn.close()


def test_persist_ingest_rejects_empty_segments(tmp_path):
    db_path = tmp_path / "empty-ingest.db"
    conn = init_db(db_path)
    book_id = str(uuid.uuid4())
    BookRepo(conn).insert(
        id=book_id,
        title="t",
        format="txt",
        file_path="/x",
        status="processing",
    )
    conn.close()

    try:
        _persist_ingest_sync(
            db_path,
            book_id=book_id,
            src=tmp_path / "sample.txt",
            metadata={},
            detected_language="zh",
            target_language="zh-CN",
            segments=[],
            ingest_meta={"total_char_count": 0},
        )
    except RuntimeError as exc:
        assert "分段结果为空" in str(exc)
    else:
        raise AssertionError("empty ingest persist must fail")

    check = connect_db(db_path)
    book = BookRepo(check).get(book_id)
    assert book["status"] == "processing"
    assert SegmentRepo(check).list_for_book(book_id, include_body=False) == []
    check.close()
