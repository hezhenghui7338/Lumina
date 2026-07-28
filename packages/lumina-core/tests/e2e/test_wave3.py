"""Wave 3 e2e: notes, news chat, quote."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumina_core.config import Settings
from lumina_core.main import create_app
from lumina_core.models.router import set_router
from lumina_core.news.store import NewsArticle, NewsSourceRepo, NewsStore
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


def test_create_note_and_search(client):
    sample = BOOK_FIXTURES / "sample.txt"
    book_id = client.post("/books/import", json={"paths": [str(sample)]}).json()["books"][0]["book_id"]

    note = client.post(
        "/notes",
        json={"book_id": book_id, "content": "反向传播要点", "type": "manual"},
    )
    assert note.status_code == 200
    assert note.json()["content"] == "反向传播要点"

    hits = client.get("/search", params={"q": "反向传播"}).json()["results"]
    assert any(h["kind"] == "note" for h in hits)


def test_chat_with_quote(client):
    sample = BOOK_FIXTURES / "sample.txt"
    book_id = client.post("/books/import", json={"paths": [str(sample)]}).json()["books"][0]["book_id"]

    for _ in range(50):
        segs = client.get(f"/books/{book_id}/segments").json()["segments"]
        if segs and segs[0]["summary_status"] == "ready":
            break
        time.sleep(0.1)

    resp = client.post(
        f"/books/{book_id}/chat",
        json={"message": "解释这段", "segment_index": 0, "quote": "段落内容"},
    )
    assert resp.status_code == 200
    assert resp.json()["answer"]


def test_news_article_chat(client):
    conn = client.app.state.lumina.conn  # type: ignore[attr-defined]
    source = NewsSourceRepo(conn).add_source("https://example.com/feed", "Example")
    NewsStore(conn).upsert(
        NewsArticle(
            id="art2",
            source_id=source["id"],
            url="https://example.com/2",
            title="Wave 3 Test",
            excerpt="Testing news deep chat.",
        )
    )

    resp = client.post(
        "/news/articles/art2/chat",
        json={"message": "这篇文章讲了什么？"},
    )
    assert resp.status_code == 200
    assert resp.json()["answer"]
