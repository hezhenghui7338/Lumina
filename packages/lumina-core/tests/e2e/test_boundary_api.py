"""E2E: manual adjacent segment boundary moves."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumina_core.config import Settings
from lumina_core.db.repos import BookRepo
from lumina_core.main import create_app
from lumina_core.models.router import set_router
from tests.support.import_helpers import wait_for_ingest
from tests.support.mock_router import MockModelRouter, load_json_fixture

pytestmark = pytest.mark.e2e

LLM_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "llm"


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
    app = create_app(Settings(data_dir=tmp_path, auto_start_summary=False))
    app.state.lumina.router = router
    app.state.lumina.job_queue.router = router
    set_router(router)
    with TestClient(app) as c:
        yield c


def _import_long_book(client: TestClient, tmp_path: Path) -> str:
    sample = tmp_path / "boundary-book.txt"
    sample.write_text(
        "\n\n".join(
            f"第 {i} 段。这是一段用于验证手动调整语义边界的测试文字，包含完整句子和稳定段落。"
            for i in range(80)
        ),
        encoding="utf-8",
    )
    book_id = client.post(
        "/books/import", json={"paths": [str(sample)]}
    ).json()["books"][0]["book_id"]
    wait_for_ingest(client, book_id)
    return book_id


def _wait_status(client, book_id: str, indices: list[int], status: str, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        segs = client.get(f"/books/{book_id}/segments").json()["segments"]
        by_idx = {s["idx"]: s for s in segs}
        if all(by_idx.get(i, {}).get("summary_status") == status for i in indices):
            return
        time.sleep(0.1)
    segs = client.get(f"/books/{book_id}/segments").json()["segments"]
    pytest.fail({i: next(s["summary_status"] for s in segs if s["idx"] == i) for i in indices})


def test_move_boundary_rewrites_pair_and_requeues_summaries(client, tmp_path):
    book_id = _import_long_book(client, tmp_path)
    listed = client.get(f"/books/{book_id}/segments").json()["segments"]
    assert len(listed) >= 2

    left = client.get(f"/books/{book_id}/segments/0").json()
    right = client.get(f"/books/{book_id}/segments/1").json()
    original = left["raw_text"] + right["raw_text"]
    note = client.post(
        "/notes",
        json={
            "book_id": book_id,
            "segment_id": right["id"],
            "content": "quote note",
            "quote": right["raw_text"][:40].strip(),
        },
    )
    assert note.status_code == 200

    preview = client.get(f"/books/{book_id}/segments/0/boundary")
    assert preview.status_code == 200
    body = preview.json()
    assert body["left_idx"] == 0
    assert body["right_idx"] == 1
    assert body["left_char_count"] == len(left["raw_text"])
    candidates = [c["offset"] for c in body["candidates"] if c["offset"] != body["left_char_count"]]
    assert candidates

    original_tail = {s["idx"]: s["summary_status"] for s in listed if s["idx"] > 1}

    moved = client.post(
        f"/books/{book_id}/segments/0/boundary",
        json={"left_char_count": candidates[0]},
    )
    assert moved.status_code == 200
    payload = moved.json()
    assert payload["unchanged"] is False
    assert payload["left_status"] == "pending"
    assert payload["right_status"] == "pending"

    new_left = client.get(f"/books/{book_id}/segments/0").json()
    new_right = client.get(f"/books/{book_id}/segments/1").json()
    assert new_left["raw_text"] + new_right["raw_text"] == original
    assert new_left["id"] == left["id"]
    assert new_right["id"] == right["id"]
    listed_after = client.get(f"/books/{book_id}/segments").json()["segments"]
    for seg in listed_after:
        if seg["idx"] > 1:
            assert seg["summary_status"] == original_tail[seg["idx"]]

    _wait_status(client, book_id, [0, 1], "ready", timeout=8.0)
    notes = client.get("/notes", params={"book_id": book_id}).json()["notes"]
    assert notes
    quote = (right["raw_text"][:40]).strip()
    if quote in new_left["raw_text"] and quote not in new_right["raw_text"]:
        assert notes[0]["segment_id"] == new_left["id"]


def test_move_boundary_same_offset_is_noop(client, tmp_path):
    book_id = _import_long_book(client, tmp_path)
    left = client.get(f"/books/{book_id}/segments/0").json()
    client.post(
        f"/books/{book_id}/segments/0/retry",
        json={"summary_tier": "normal"},
    )
    _wait_status(client, book_id, [0], "ready", timeout=8.0)

    same = client.post(
        f"/books/{book_id}/segments/0/boundary",
        json={"left_char_count": len(left["raw_text"])},
    )
    assert same.status_code == 200
    assert same.json()["unchanged"] is True
    after = client.get(f"/books/{book_id}/segments/0").json()
    assert after["summary_status"] == "ready"
    assert after["raw_text"] == left["raw_text"]


def test_move_boundary_rejects_missing_and_processing(client, tmp_path):
    missing = client.get("/books/missing/segments/0/boundary")
    assert missing.status_code == 404

    book_id = _import_long_book(client, tmp_path)
    last_idx = client.get(f"/books/{book_id}").json()["segment_count"] - 1
    no_right = client.post(
        f"/books/{book_id}/segments/{last_idx}/boundary",
        json={"left_char_count": 10},
    )
    assert no_right.status_code == 404

    BookRepo(client.app.state.lumina.conn).update(book_id, status="processing")
    conflict = client.post(
        f"/books/{book_id}/segments/0/boundary",
        json={"left_char_count": 10},
    )
    assert conflict.status_code == 409
