"""Shared SQLite connection must serialize cross-thread access."""

from __future__ import annotations

import threading
import time
import uuid

from lumina_core.db.repos import BookRepo, SegmentRepo
from lumina_core.db.schema import init_db
from lumina_core.jobs.ingest import _persist_ingest_sync


def test_concurrent_get_during_persist_ingest(tmp_path):
    """Regression: unlocked reads raced ingest to_thread writes → InterfaceError."""
    conn = init_db(tmp_path / "lock.db")
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
            conn,
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
