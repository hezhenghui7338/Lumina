"""Local performance JSONL recorder."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumina_core.config import Settings
from lumina_core.db.schema import init_db
from lumina_core.main import create_app
from lumina_core.perf import (
    InstrumentedConnection,
    get_recorder,
    instrument_connection,
    record,
    sql_label,
    start,
    stop,
)


def _read_jsonl(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


@pytest.fixture(autouse=True)
def _stop_perf_after_test():
    yield
    stop()


def test_sql_label_select():
    name, clipped = sql_label("SELECT id, title FROM books WHERE id = ?")
    assert name == "SELECT books"
    assert "books" in clipped
    assert "?" in clipped or "WHERE" in clipped


def test_two_starts_create_distinct_files(tmp_path: Path):
    p1 = start(tmp_path)
    record(kind="op", name="a", ms=1.0)
    get_recorder().flush(timeout=2.0)
    p2 = start(tmp_path)
    assert p1 != p2
    assert p1.exists()
    assert p2.exists()
    assert p1.parent == tmp_path / "perf"


def test_record_writes_jsonl(tmp_path: Path):
    path = start(tmp_path)
    record(kind="op", name="manual", ms=12.5, extra="x")
    get_recorder().flush(timeout=2.0)
    rows = _read_jsonl(path)
    assert rows[0]["kind"] == "session"
    assert rows[0]["name"] == "start"
    matching = [r for r in rows if r.get("name") == "manual"]
    assert len(matching) == 1
    assert matching[0]["ms"] == 12.5
    assert matching[0]["extra"] == "x"
    assert matching[0]["ts"].endswith("Z")


def test_http_request_logged(tmp_path: Path):
    app = create_app(Settings(data_dir=tmp_path))
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    path = get_recorder().path
    assert path is not None
    get_recorder().flush(timeout=2.0)
    rows = _read_jsonl(path)
    http_rows = [r for r in rows if r.get("kind") == "http" and r.get("path") == "/health"]
    assert http_rows, rows
    assert http_rows[-1]["method"] == "GET"
    assert http_rows[-1]["status"] == 200
    assert "ms" in http_rows[-1]
    op_names = {r["name"] for r in rows if r.get("kind") == "op"}
    assert "startup.total" in op_names


def test_db_execute_logged(tmp_path: Path):
    start(tmp_path)
    conn = init_db(tmp_path / "t.db")
    conn.execute("SELECT 1 AS n")
    get_recorder().flush(timeout=2.0)
    path = get_recorder().path
    assert path is not None
    rows = _read_jsonl(path)
    db_rows = [r for r in rows if r.get("kind") == "db"]
    assert db_rows, rows
    assert any(r.get("op") == "execute" for r in db_rows)


def test_instrumented_connection_supports_context_manager(tmp_path: Path):
    """sqlite3 uses `with conn:` for commit/rollback; proxy must implement it."""
    import sqlite3

    raw = sqlite3.connect(tmp_path / "ctx.db")
    conn = instrument_connection(raw)
    assert isinstance(conn, InstrumentedConnection)
    with conn as entered:
        assert entered is conn
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.execute("INSERT INTO t (id) VALUES (1)")
    rows = conn.execute("SELECT id FROM t").fetchall()
    assert rows == [(1,)]
    conn.close()


def test_record_does_not_block_on_slow_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = start(tmp_path)
    recorder = get_recorder()
    write_gate = threading.Event()

    def slow_write_buf(buf: list[str]) -> None:
        write_gate.wait(timeout=2.0)
        if recorder._file is None:
            return
        recorder._file.write("\n".join(buf) + "\n")
        recorder._file.flush()

    monkeypatch.setattr(recorder, "_write_buf", slow_write_buf)
    # Fill a few items so writer is busy; callers must still return quickly.
    t0 = time.perf_counter()
    for i in range(50):
        record(kind="op", name=f"burst-{i}", ms=float(i))
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.2, elapsed
    assert path.exists()
    write_gate.set()
    recorder.flush(timeout=2.0)
