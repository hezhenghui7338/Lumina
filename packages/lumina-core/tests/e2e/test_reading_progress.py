"""Reading progress (current_segment_index) e2e tests."""

from __future__ import annotations

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
    app = create_app(Settings(data_dir=tmp_path))
    app.state.lumina.router = router
    app.state.lumina.job_queue.router = router
    set_router(router)
    with TestClient(app) as c:
        yield c


def _import_sample(client: TestClient) -> str:
    return import_sample_book(client)


def _insert_multi_segment_book(client: TestClient, *, segment_count: int = 10) -> str:
    import uuid
    from datetime import datetime, timezone

    conn = client.app.state.lumina.conn  # type: ignore[attr-defined]
    book_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO books (
          id, title, format, file_path, segment_count, status,
          file_hash, current_segment_index, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (book_id, "Multi", "txt", f"/tmp/{book_id}.txt", segment_count, "reading", book_id, 0, now, now),
    )
    for idx in range(segment_count):
        conn.execute(
            """
            INSERT INTO segments (
              id, book_id, idx, anchor_label, raw_text, char_count,
              summary_status, retry_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (f"{book_id}-s{idx}", book_id, idx, f"段 {idx + 1}", f"text {idx}", 8, "pending", 0),
        )
    conn.commit()
    return book_id


def test_open_returns_current_segment_index(client):
    book_id = _insert_multi_segment_book(client, segment_count=10)

    client.patch(
        f"/books/{book_id}/reading-progress",
        json={"segment_index": 3},
    )

    open_resp = client.post(f"/books/{book_id}/open")
    assert open_resp.status_code == 200
    body = open_resp.json()
    assert body["status"] == "opened"
    assert body["current_segment_index"] == 3


def test_patch_reading_progress_persists(client):
    book_id = _insert_multi_segment_book(client, segment_count=10)

    resp = client.patch(
        f"/books/{book_id}/reading-progress",
        json={"segment_index": 2},
    )
    assert resp.status_code == 200
    assert resp.json()["current_segment_index"] == 2

    book = client.get(f"/books/{book_id}").json()
    assert book["current_segment_index"] == 2


def test_patch_reading_progress_404_for_missing_book(client):
    resp = client.patch(
        "/books/nonexistent-id/reading-progress",
        json={"segment_index": 1},
    )
    assert resp.status_code == 404


def test_patch_reading_progress_rejects_out_of_range(client):
    book_id = _insert_multi_segment_book(client, segment_count=5)
    segment_count = client.get(f"/books/{book_id}").json()["segment_count"]
    assert segment_count == 5

    resp = client.patch(
        f"/books/{book_id}/reading-progress",
        json={"segment_index": segment_count + 10},
    )
    assert resp.status_code == 400

    resp = client.patch(
        f"/books/{book_id}/reading-progress",
        json={"segment_index": -1},
    )
    assert resp.status_code == 400
