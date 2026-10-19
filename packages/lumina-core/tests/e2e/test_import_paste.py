"""Pasted text becomes an offline book without blocking segmentation."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumina_core.config import Settings
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
    app = create_app(Settings(data_dir=tmp_path))
    app.state.lumina.router = router
    app.state.lumina.job_queue.router = router
    set_router(router)
    with TestClient(app) as c:
        yield c


def test_import_paste_returns_processing_and_keeps_text(client):
    resp = client.post(
        "/books/import-paste",
        json={"text": "粘贴标题\n这是粘进来的正文，应当进入分段。"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "processing"
    assert body["title"] == "粘贴标题"
    book_id = body["book_id"]
    finished = wait_for_ingest(client, book_id)
    assert finished["status"] in ("unread", "reading", "summarized")
    assert finished["title"] == "粘贴标题"
    segment = client.get(f"/books/{book_id}/segments/0").json()
    assert "粘进来的正文" in (segment.get("raw_text") or "")


def test_import_paste_duplicate_is_conflict_until_overwrite(client):
    text = "同一篇\n重复导入用的正文。"
    first = client.post("/books/import-paste", json={"text": text})
    assert first.status_code == 200
    again = client.post("/books/import-paste", json={"text": text + "\r\n"})
    assert again.status_code == 409
    assert again.json()["detail"]["existing_book_id"] == first.json()["book_id"]
    overwritten = client.post(
        "/books/import-paste",
        json={"text": text, "overwrite": True},
    )
    assert overwritten.status_code == 200
    assert overwritten.json()["book_id"] != first.json()["book_id"]


def test_import_paste_rejects_blank_without_creating_a_book(client):
    resp = client.post("/books/import-paste", json={"text": "  \n"})
    assert resp.status_code == 400
    assert client.get("/books").json()["books"] == []
