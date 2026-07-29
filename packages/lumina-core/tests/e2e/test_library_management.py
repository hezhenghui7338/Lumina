"""Library management API e2e tests."""

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
            "summarize": {"category": "文学"},
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


def _import_book_id(client: TestClient) -> str:
    return import_sample_book(client)


def test_list_books_filter_and_patch_favorite(client):
    book_id = _import_sample(client)
    client.post(f"/books/{book_id}/open")

    reading = client.get("/books", params={"collection": "reading"}).json()["books"]
    assert any(b["id"] == book_id for b in reading)

    patched = client.patch(
        f"/books/{book_id}",
        json={"is_favorite": True, "title": "新标题"},
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["is_favorite"] is True
    assert body["title"] == "新标题"

    favorites = client.get("/books", params={"sort": "favorite"}).json()["books"]
    assert favorites[0]["id"] == book_id


def test_classify_and_delete_book(client, tmp_path):
    book_id = _import_sample(client)
    assert client.post(f"/books/{book_id}/classify").status_code == 200

    category = None
    for _ in range(30):
        book = client.get(f"/books/{book_id}").json()
        category = book.get("category")
        if category:
            break
        time.sleep(0.05)
    assert category == "文学"

    books_dir = tmp_path / "books" / book_id
    assert books_dir.exists()

    assert client.delete(f"/books/{book_id}").status_code == 200
    assert client.get(f"/books/{book_id}").status_code == 404
    assert not books_dir.exists()


def test_open_book_unread_to_reading(client):
    book_id = _import_book_id(client)
    conn = client.app.state.lumina.conn
    conn.execute("UPDATE books SET status = 'unread' WHERE id = ?", (book_id,))
    conn.commit()
    assert client.get(f"/books/{book_id}").json()["status"] == "unread"

    assert client.post(f"/books/{book_id}/open").status_code == 200
    assert client.get(f"/books/{book_id}").json()["status"] == "reading"


def test_open_book_preserves_summarized(client):
    book_id = _import_book_id(client)
    conn = client.app.state.lumina.conn
    conn.execute(
        "UPDATE books SET status = 'summarized' WHERE id = ?",
        (book_id,),
    )
    conn.execute(
        "UPDATE segments SET summary_status = 'ready' WHERE book_id = ?",
        (book_id,),
    )
    conn.commit()

    assert client.get(f"/books/{book_id}").json()["status"] == "summarized"

    assert client.post(f"/books/{book_id}/open").status_code == 200
    book = client.get(f"/books/{book_id}").json()
    assert book["status"] == "summarized"
    assert book["last_opened_at"] is not None

    summarized = client.get("/books", params={"collection": "summarized"}).json()["books"]
    assert any(b["id"] == book_id for b in summarized)


def test_reader_bootstrap_flow(client):
    """ReaderView.load: fetchBook + settings + openBook + listSegments."""
    book_id = _import_sample(client)

    book_resp = client.get(f"/books/{book_id}")
    assert book_resp.status_code == 200
    book = book_resp.json()
    assert book["status"] != "processing"

    settings_resp = client.get("/settings")
    assert settings_resp.status_code == 200
    assert isinstance(settings_resp.json()["target_language"], str)

    open_resp = client.post(f"/books/{book_id}/open")
    assert open_resp.status_code == 200
    assert open_resp.json()["status"] == "opened"

    seg_resp = client.get(f"/books/{book_id}/segments")
    assert seg_resp.status_code == 200
    segments = seg_resp.json()["segments"]
    assert segments
    first = segments[0]
    assert "raw_text" not in first
    assert "translation" not in first
    assert "char_count" in first
    assert "summary_provider" in first
    assert "summary_model" in first
