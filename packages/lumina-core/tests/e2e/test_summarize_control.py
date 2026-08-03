"""Summarize start/stop/retry API smoke tests."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumina_core.config import Settings
from lumina_core.main import create_app
from lumina_core.models.router import set_router
from tests.support.import_helpers import import_sample_book
from tests.support.mock_router import MockModelRouter, load_json_fixture

pytestmark = pytest.mark.e2e

LLM_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "llm"
BOOK_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "books"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMINA_DATA_DIR", str(tmp_path))
    router = MockModelRouter(
        responses={
            "summarize": load_json_fixture(LLM_FIXTURES / "summary_segment0.json"),
            "chat": load_json_fixture(LLM_FIXTURES / "chat_with_citation.json"),
            "translate": "示例译文。",
        }
    )
    app = create_app(Settings(data_dir=tmp_path, auto_start_summary=True))
    app.state.lumina.router = router
    app.state.lumina.job_queue.router = router
    set_router(router)
    with TestClient(app) as c:
        yield c


def _wait_ready(client, book_id: str, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        segs = client.get(f"/books/{book_id}/segments").json()["segments"]
        if segs and all(s["summary_status"] == "ready" for s in segs):
            return
        time.sleep(0.1)
    statuses = [s["summary_status"] for s in client.get(f"/books/{book_id}/segments").json()["segments"]]
    pytest.fail(f"not ready: {statuses}")


def test_summarize_stop_and_start_book(client):
    book_id = import_sample_book(client)

    stop = client.post(f"/books/{book_id}/summarize/stop")
    assert stop.status_code == 200
    assert stop.json()["status"] == "stopped"

    start = client.post(f"/books/{book_id}/summarize/start")
    assert start.status_code == 200
    assert start.json()["status"] == "started"
    _wait_ready(client, book_id)


def test_summarize_stop_and_start_all(client):
    book_id = import_sample_book(client)

    stop = client.post("/books/summarize/stop")
    assert stop.status_code == 200
    assert stop.json()["scope"] == "all"

    start = client.post("/books/summarize/start")
    assert start.status_code == 200
    assert start.json()["scope"] == "all"
    _wait_ready(client, book_id)


def test_summarize_batch_stop_and_start(client):
    book_id = import_sample_book(client)

    stop = client.post("/books/summarize/stop", json={"book_ids": [book_id]})
    assert stop.status_code == 200
    assert stop.json()["scope"] == "batch"
    assert stop.json()["affected_count"] == 1

    start = client.post("/books/summarize/start", json={"book_ids": [book_id]})
    assert start.status_code == 200
    assert start.json()["scope"] == "batch"
    _wait_ready(client, book_id)


def test_retry_segment_after_stop(client):
    book_id = import_sample_book(client)
    assert client.post(f"/books/{book_id}/summarize/stop").status_code == 200

    retry = client.post(f"/books/{book_id}/segments/0/retry")
    assert retry.status_code == 200
    assert retry.json()["status"] == "queued"

    for _ in range(50):
        seg = client.get(f"/books/{book_id}/segments/0").json()
        if seg["summary_status"] == "ready":
            return
        time.sleep(0.1)
    pytest.fail("retry did not complete")


def test_retry_multiple_segments(client):
    book_id = import_sample_book(client)
    _wait_ready(client, book_id)

    resp = client.post(
        f"/books/{book_id}/segments/retry",
        json={"indices": [0, 0]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "queued"
    assert body["count"] == 1

    for _ in range(50):
        seg = client.get(f"/books/{book_id}/segments/0").json()
        if seg["summary_status"] == "ready":
            return
        time.sleep(0.1)
    pytest.fail("segment 0 did not become ready after bulk retry")


def test_regenerate_book_reruns_ready_segments(client):
    book_id = import_sample_book(client)
    _wait_ready(client, book_id)

    segs_before = client.get(f"/books/{book_id}/segments").json()["segments"]
    assert all(s["summary_status"] == "ready" for s in segs_before)

    # summarize/start only resumes pending/failed — should not re-queue ready segments.
    assert client.post(f"/books/{book_id}/summarize/stop").status_code == 200
    start = client.post(f"/books/{book_id}/summarize/start")
    assert start.status_code == 200
    time.sleep(0.2)
    segs_after_start = client.get(f"/books/{book_id}/segments").json()["segments"]
    assert all(s["summary_status"] == "ready" for s in segs_after_start)

    regen = client.post(f"/books/{book_id}/summarize/regenerate")
    assert regen.status_code == 200
    body = regen.json()
    assert body["status"] == "queued"
    assert body["count"] == len(segs_before)

    for _ in range(80):
        segs = client.get(f"/books/{book_id}/segments").json()["segments"]
        if all(s["summary_status"] == "ready" for s in segs):
            return
        time.sleep(0.1)
    statuses = [s["summary_status"] for s in client.get(f"/books/{book_id}/segments").json()["segments"]]
    pytest.fail(f"regenerate did not complete: {statuses}")


def test_start_book_resumes_failed_segment(client):
    book_id = import_sample_book(client)
    _wait_ready(client, book_id)

    from lumina_core.db.repos import SegmentRepo

    conn = client.app.state.lumina.conn  # type: ignore[attr-defined]
    seg = SegmentRepo(conn).get_by_index(book_id, 0)
    assert seg is not None
    SegmentRepo(conn).set_status(seg["id"], "failed", retry_count=3)

    start = client.post(f"/books/{book_id}/summarize/start")
    assert start.status_code == 200
    assert start.json()["status"] == "started"

    for _ in range(80):
        updated = client.get(f"/books/{book_id}/segments/0").json()
        if updated["summary_status"] == "ready":
            return
        time.sleep(0.1)
    pytest.fail(
        "failed segment 0 did not become ready after summarize/start: "
        f"{client.get(f'/books/{book_id}/segments/0').json()['summary_status']}"
    )
