"""Import + summarize spike tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumina_core.config import Settings
from lumina_core.main import create_app
from lumina_core.models.router import set_router
from tests.support.import_helpers import import_sample_book, wait_for_ingest
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


def test_import_returns_processing_immediately(client):
    sample = BOOK_FIXTURES / "sample.txt"
    resp = client.post("/books/import", json={"paths": [str(sample)]})
    assert resp.status_code == 200
    body = resp.json()["books"][0]
    assert body["status"] == "processing"
    book_id = body["book_id"]
    listed = client.get("/books").json()["books"]
    assert any(b["id"] == book_id for b in listed)
    finished = wait_for_ingest(client, book_id)
    assert finished["status"] in ("unread", "reading", "summarized")
    assert finished.get("segment_count", 0) > 0


def test_import_txt_triggers_prefetch(client, tmp_path):
    sample = BOOK_FIXTURES / "sample.txt"
    resp = client.post("/books/import", json={"paths": [str(sample)]})
    assert resp.status_code == 200
    book_id = resp.json()["books"][0]["book_id"]
    wait_for_ingest(client, book_id)

    import time

    for _ in range(50):
        segs = client.get(f"/books/{book_id}/segments").json()["segments"]
        if segs and segs[0]["summary_status"] == "ready":
            break
        time.sleep(0.1)

    # List API is meta-only (never-freeze): no raw_text payload.
    list_seg = client.get(f"/books/{book_id}/segments").json()["segments"][0]
    assert "raw_text" not in list_seg or list_seg.get("raw_text") is None

    seg0 = client.get(f"/books/{book_id}/segments/0").json()
    assert seg0["summary_status"] == "ready"
    assert seg0.get("raw_text")
    summary = json.loads(seg0["summary_json"])
    assert "sentences" in summary
    assert seg0["label"]


def test_import_duplicate_returns_409(client, tmp_path):
    sample = BOOK_FIXTURES / "sample.txt"
    book_id = client.post("/books/import", json={"paths": [str(sample)]}).json()["books"][0]["book_id"]
    wait_for_ingest(client, book_id)
    resp = client.post("/books/import", json={"paths": [str(sample)]})
    assert resp.status_code == 409
    assert "existing_book_id" in resp.json()["detail"]


def test_import_overwrite_purges_old_data(client, tmp_path):
    sample = BOOK_FIXTURES / "sample.txt"
    old_book_id = client.post("/books/import", json={"paths": [str(sample)]}).json()["books"][0]["book_id"]
    wait_for_ingest(client, old_book_id)

    segments = client.get(f"/books/{old_book_id}/segments").json()["segments"]
    assert segments
    seg_id = segments[0]["id"]
    note_resp = client.post(
        "/notes",
        json={
            "book_id": old_book_id,
            "segment_id": seg_id,
            "content": "overwrite test note",
        },
    )
    assert note_resp.status_code == 200

    old_books_dir = tmp_path / "books" / old_book_id
    assert old_books_dir.exists()

    resp = client.post(
        "/books/import",
        json={"paths": [str(sample)], "overwrite": True},
    )
    assert resp.status_code == 200
    new_book_id = resp.json()["books"][0]["book_id"]
    assert new_book_id != old_book_id

    assert client.get(f"/books/{old_book_id}").status_code == 404
    assert not old_books_dir.exists()

    conn = client.app.state.lumina.conn
    old_seg_count = conn.execute(
        "SELECT COUNT(*) AS c FROM segments WHERE book_id = ?",
        (old_book_id,),
    ).fetchone()["c"]
    old_note_count = conn.execute(
        "SELECT COUNT(*) AS c FROM notes WHERE book_id = ?",
        (old_book_id,),
    ).fetchone()["c"]
    assert old_seg_count == 0
    assert old_note_count == 0

    finished = wait_for_ingest(client, new_book_id)
    assert finished.get("segment_count", 0) > 0
    notes = client.get("/notes", params={"book_id": new_book_id}).json()["notes"]
    assert notes == []


def test_chat_json_mode(client, tmp_path):
    sample = BOOK_FIXTURES / "sample.txt"
    book_id = client.post("/books/import", json={"paths": [str(sample)]}).json()["books"][0]["book_id"]
    wait_for_ingest(client, book_id)

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
    wait_for_ingest(client, book_id)
    import time

    for _ in range(50):
        segs = client.get(f"/books/{book_id}/segments").json()["segments"]
        if segs and segs[0]["summary_status"] == "ready":
            break
        time.sleep(0.1)

    resp = client.post(f"/books/{book_id}/export", json={"include_notes": False})
    assert resp.status_code == 200
    assert "摘要版" in resp.text


def test_export_chinese_title_returns_200(client, tmp_path):
    sample = BOOK_FIXTURES / "sample.txt"
    book_id = client.post("/books/import", json={"paths": [str(sample)]}).json()["books"][0]["book_id"]
    wait_for_ingest(client, book_id)
    import time

    for _ in range(50):
        segs = client.get(f"/books/{book_id}/segments").json()["segments"]
        if segs and segs[0]["summary_status"] == "ready":
            break
        time.sleep(0.1)

    patch = client.patch(f"/books/{book_id}", json={"title": "三体"})
    assert patch.status_code == 200

    resp = client.post(f"/books/{book_id}/export", json={"include_notes": False})
    assert resp.status_code == 200
    assert "摘要版" in resp.text
    disposition = resp.headers.get("Content-Disposition", "")
    assert "filename" in disposition
    disposition.encode("latin-1")


def test_settings_roundtrip(client):
    resp = client.put(
        "/settings",
        json={
            "target_language": "en-US",
            "web_search_provider": "tavily",
            "tavily_api_key": "tvly-secret",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["target_language"] == "en-US"
    assert body["web_search_provider"] == "tavily"
    assert body["tavily_api_key"] == "***"

    # Masked PUT keeps in-memory key; invalid provider falls back to ddgs
    resp2 = client.put(
        "/settings",
        json={"web_search_provider": "nope", "tavily_api_key": "***"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["web_search_provider"] == "ddgs"
    assert resp2.json()["tavily_api_key"] == "***"


def test_settings_secrets_persist_across_reload(client, tmp_path):
    resp = client.put(
        "/settings",
        json={
            "web_search_provider": "tavily",
            "tavily_api_key": "tvly-persist",
            "models": {
                "resources": [
                    {
                        "id": "openai",
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "sk-persist",
                    }
                ],
                "chat": {"priority": ["openai"]},
                "summarize": {"priority": ["ollama"]},
            },
        },
    )
    assert resp.status_code == 200

    secrets_file = tmp_path / "secrets.json"
    assert secrets_file.exists()
    secrets = json.loads(secrets_file.read_text(encoding="utf-8"))
    assert secrets["resources"]["openai"] == "sk-persist"
    assert secrets["tavily"] == "tvly-persist"

    from lumina_core.settings_store import load_models, load_settings

    reloaded_settings = load_settings(tmp_path)
    reloaded_models = load_models(tmp_path)
    assert reloaded_settings.web_search_provider == "tavily"
    assert reloaded_settings.tavily_api_key == "tvly-persist"
    openai = reloaded_models.resource_by_id("openai")
    assert openai is not None
    assert openai.api_key == "sk-persist"


def test_settings_models_persist_and_redact(client, tmp_path):
    payload = {
        "models": {
            "resources": [
                {
                    "id": "openai",
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "sk-test-secret",
                    "concurrency": 4,
                },
                {
                    "id": "ollama",
                    "provider": "ollama",
                    "model": "qwen3.5:9b",
                    "base_url": "http://127.0.0.1:11434",
                    "concurrency": 1,
                },
            ],
            "chat": {"priority": ["openai"]},
            "summarize": {"priority": ["ollama"]},
        }
    }
    resp = client.put("/settings", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    openai = next(r for r in body["models"]["resources"] if r["id"] == "openai")
    ollama = next(r for r in body["models"]["resources"] if r["id"] == "ollama")
    assert openai["api_key"] == "***"
    assert openai["model"] == "gpt-4o-mini"
    assert openai["concurrency"] == 4
    assert ollama["model"] == "qwen3.5:9b"
    assert ollama["concurrency"] == 1

    disk = json.loads((tmp_path / "models.json").read_text(encoding="utf-8"))
    disk_openai = next(r for r in disk["resources"] if r["id"] == "openai")
    assert disk_openai["api_key"] is None
    assert "job_concurrency" not in disk
    assert next(r for r in disk["resources"] if r["id"] == "ollama")["model"] == "qwen3.5:9b"

    resp2 = client.put(
        "/settings",
        json={
            "models": {
                **payload["models"],
                "resources": [
                    {**payload["models"]["resources"][0], "api_key": "***", "model": "gpt-4o"},
                    payload["models"]["resources"][1],
                ],
            }
        },
    )
    assert resp2.status_code == 200
    openai2 = next(r for r in resp2.json()["models"]["resources"] if r["id"] == "openai")
    assert openai2["api_key"] == "***"
    assert openai2["model"] == "gpt-4o"
