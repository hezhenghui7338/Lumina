"""Long-book reopen: slim segment list + reading progress recovery."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from lumina_core.config import Settings
from lumina_core.main import create_app
from lumina_core.models.router import set_router
from tests.support.mock_router import MockModelRouter, load_json_fixture

pytestmark = pytest.mark.e2e

LLM_FIXTURES = __import__("pathlib").Path(__file__).resolve().parents[1] / "fixtures" / "llm"


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


def _insert_long_book(client: TestClient, *, segment_count: int = 500) -> str:
    conn = client.app.state.lumina.conn  # type: ignore[attr-defined]
    book_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    summary_blob = json.dumps(
        {
            "sentences": ["本段交代了主要情节。" * 5],
            "bullets": ["要点一", "要点二", "要点三"],
            "anchor": "段锚点",
        },
        ensure_ascii=False,
    )
    conn.execute(
        """
        INSERT INTO books (
          id, title, format, file_path, segment_count, status,
          file_hash, current_segment_index, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            book_id,
            "Long Novel",
            "txt",
            f"/tmp/{book_id}.txt",
            segment_count,
            "reading",
            book_id,
            0,
            now,
            now,
        ),
    )
    for idx in range(segment_count):
        conn.execute(
            """
            INSERT INTO segments (
              id, book_id, idx, anchor_label, raw_text, char_count,
              summary_json, label, summary_status, retry_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{book_id}-s{idx}",
                book_id,
                idx,
                f"段 {idx + 1}",
                f"正文内容 {idx} " * 200,
                1600,
                summary_blob,
                f"段 {idx + 1} 摘要",
                "ready",
                0,
            ),
        )
    conn.commit()
    return book_id


def test_long_book_slim_list_excludes_summary_json(client):
    book_id = _insert_long_book(client, segment_count=500)

    resp = client.get(f"/books/{book_id}/segments")
    assert resp.status_code == 200
    segments = resp.json()["segments"]
    assert len(segments) == 500
    assert "summary_json" not in segments[0]
    assert segments[0]["summary_status"] == "ready"
    assert segments[0]["label"]

    # Slim list should stay well under 1 MB even with 500 ready segments.
    assert len(resp.content) < 1_000_000


def test_long_book_reopen_restores_progress(client):
    book_id = _insert_long_book(client, segment_count=500)
    saved_idx = 250

    patch = client.patch(
        f"/books/{book_id}/reading-progress",
        json={"segment_index": saved_idx},
    )
    assert patch.status_code == 200

    open_resp = client.post(f"/books/{book_id}/open")
    assert open_resp.status_code == 200
    assert open_resp.json()["current_segment_index"] == saved_idx

    list_resp = client.get(f"/books/{book_id}/segments")
    assert list_resp.status_code == 200
    indices = {s["idx"] for s in list_resp.json()["segments"]}
    assert saved_idx in indices

    detail = client.get(f"/books/{book_id}/segments/{saved_idx}")
    assert detail.status_code == 200
    body = detail.json()
    assert body.get("summary_json")
    assert body["idx"] == saved_idx
