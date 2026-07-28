"""Import + summarize spike tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumina_core.config import Settings
from lumina_core.main import create_app
from lumina_core.models.router import set_router
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


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_import_txt_triggers_prefetch(client, tmp_path):
    sample = BOOK_FIXTURES / "sample.txt"
    resp = client.post("/books/import", json={"paths": [str(sample)]})
    assert resp.status_code == 200
    book_id = resp.json()["books"][0]["book_id"]

    import time

    for _ in range(50):
        segs = client.get(f"/books/{book_id}/segments").json()["segments"]
        if segs and segs[0]["summary_status"] == "ready":
            break
        time.sleep(0.1)

    seg0 = client.get(f"/books/{book_id}/segments/0").json()
    assert seg0["summary_status"] == "ready"
    summary = json.loads(seg0["summary_json"])
    assert "sentences" in summary
    assert seg0["label"]


def test_import_duplicate_returns_409(client, tmp_path):
    sample = BOOK_FIXTURES / "sample.txt"
    assert client.post("/books/import", json={"paths": [str(sample)]}).status_code == 200
    resp = client.post("/books/import", json={"paths": [str(sample)]})
    assert resp.status_code == 409
    assert "existing_book_id" in resp.json()["detail"]


def test_chat_json_mode(client, tmp_path):
    sample = BOOK_FIXTURES / "sample.txt"
    book_id = client.post("/books/import", json={"paths": [str(sample)]}).json()["books"][0]["book_id"]

    import time

    for _ in range(50):
        segs = client.get(f"/books/{book_id}/segments").json()["segments"]
        if segs and segs[0]["summary_status"] == "ready":
            break
        time.sleep(0.1)

    chat = client.post(
        f"/books/{book_id}/chat",
        json={"message": "这段讲了什么？", "segment_index": 0},
    )
    assert chat.status_code == 200
    body = chat.json()
    assert "answer" in body
    assert body["citations"]


def test_export_markdown(client, tmp_path):
    sample = BOOK_FIXTURES / "sample.txt"
    book_id = client.post("/books/import", json={"paths": [str(sample)]}).json()["books"][0]["book_id"]
    import time

    for _ in range(50):
        segs = client.get(f"/books/{book_id}/segments").json()["segments"]
        if segs and segs[0]["summary_status"] == "ready":
            break
        time.sleep(0.1)

    resp = client.post(f"/books/{book_id}/export", json={"include_notes": False})
    assert resp.status_code == 200
    assert "摘要版" in resp.text


def test_settings_roundtrip(client):
    resp = client.put("/settings", json={"target_language": "en-US", "web_search_enabled": False})
    assert resp.status_code == 200
    assert resp.json()["target_language"] == "en-US"
    assert resp.json()["web_search_enabled"] is False
