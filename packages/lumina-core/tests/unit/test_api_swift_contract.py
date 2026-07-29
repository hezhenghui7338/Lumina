"""E2E-BOOT-01: Startup API JSON contract for Swift CoreClient decoding."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumina_core.config import Settings
from lumina_core.db.repos import SegmentRepo
from lumina_core.main import create_app
from lumina_core.models.router import set_router
from tests.support.import_helpers import import_sample_book
from tests.support.mock_router import MockModelRouter, load_json_fixture

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


def test_books_list_is_favorite_is_json_bool(client):
    """GET /books must emit JSON bool for is_favorite (Swift BookSummary)."""
    book_id = _import_sample(client)
    client.patch(f"/books/{book_id}", json={"is_favorite": True})

    books = client.get("/books").json()["books"]
    assert books
    fav = books[0]["is_favorite"]
    assert isinstance(fav, bool)
    assert fav is True


def test_books_patch_returns_bool_favorite(client):
    book_id = _import_sample(client)

    patched = client.patch(f"/books/{book_id}", json={"is_favorite": True})
    assert patched.status_code == 200
    assert patched.json()["is_favorite"] is True

    cleared = client.patch(f"/books/{book_id}", json={"is_favorite": False})
    assert cleared.status_code == 200
    assert cleared.json()["is_favorite"] is False


def test_books_get_returns_bool_favorite(client):
    book_id = _import_sample(client)
    client.patch(f"/books/{book_id}", json={"is_favorite": True})

    book = client.get(f"/books/{book_id}").json()
    assert isinstance(book["is_favorite"], bool)
    assert book["is_favorite"] is True


def test_books_list_summary_progress_matches_get(client):
    """GET /books must return live summary_ready_count (library progress bar)."""
    book_id = _import_sample(client)
    client.post(f"/books/{book_id}/summarize/stop")

    conn = client.app.state.lumina.conn  # type: ignore[attr-defined]
    seg = SegmentRepo(conn).get_by_index(book_id, 0)
    assert seg is not None
    SegmentRepo(conn).set_status(seg["id"], "ready")

    detail = client.get(f"/books/{book_id}").json()
    listed = next(b for b in client.get("/books").json()["books"] if b["id"] == book_id)

    assert detail["summary_ready_count"] == 1
    assert detail["summary_total_count"] == 1
    assert listed["summary_ready_count"] == detail["summary_ready_count"]
    assert listed["summary_total_count"] == detail["summary_total_count"]

    patched = client.patch(f"/books/{book_id}", json={"is_favorite": True}).json()
    assert patched["summary_ready_count"] == detail["summary_ready_count"]
    assert patched["summary_total_count"] == detail["summary_total_count"]


def test_settings_matches_swift_app_settings(client):
    """GET /settings shape matches Swift AppSettings / resource pool."""
    body = client.get("/settings").json()
    assert isinstance(body["target_language"], str)
    assert isinstance(body["web_search_provider"], str)
    assert body.get("debug_mode") is False
    models = body["models"]
    assert isinstance(models["resources"], list)
    for resource in models["resources"]:
        assert isinstance(resource["id"], str)
        assert isinstance(resource["provider"], str)
        assert isinstance(resource["model"], str)
    for profile in ("chat", "summarize"):
        route = models[profile]
        assert isinstance(route["priority"], list)
        assert all(isinstance(item, str) for item in route["priority"])


def test_news_brief_matches_swift_news_brief(client):
    """GET /news/brief shape matches Swift NewsBrief / NewsArticleCard."""
    brief = client.get("/news/brief").json()
    assert isinstance(brief["date"], str)
    assert isinstance(brief["count"], int)
    assert isinstance(brief["articles"], list)
    for article in brief["articles"]:
        assert isinstance(article["id"], str)
        assert isinstance(article["title"], str)
        assert isinstance(article["url"], str)
        assert isinstance(article["viewpoints"], list)
        assert isinstance(article["quotes"], list)
        assert isinstance(article["meta"], dict)
        assert isinstance(article["reasons"], list)
        if article.get("source_id") is not None:
            assert isinstance(article["source_id"], str)
        if article.get("source_title") is not None:
            assert isinstance(article["source_title"], str)


def test_news_brief_limit_query_param(client):
    brief = client.get("/news/brief", params={"limit": 10}).json()
    assert isinstance(brief["count"], int)
    assert brief["count"] <= 10

    bad = client.get("/news/brief", params={"limit": 3})
    assert bad.status_code == 422


def test_news_sources_is_preset_and_restore(client):
    listed = client.get("/news/sources").json()
    assert len(listed["sources"]) == 3
    assert all("is_preset" in s for s in listed["sources"])
    assert all(s["is_preset"] is True for s in listed["sources"])

    dup = client.post(
        "/news/sources",
        json={"url": listed["sources"][0]["url"], "title": "Dup"},
    )
    assert dup.status_code == 409

    bad_url = client.post("/news/sources", json={"url": "ftp://bad.example/feed"})
    assert bad_url.status_code == 400

    custom = client.post(
        "/news/sources",
        json={"url": "https://example.com/my-feed.xml", "title": "Custom"},
    )
    assert custom.status_code == 200
    assert custom.json()["is_preset"] is False

    delete_id = listed["sources"][0]["id"]
    assert client.delete(f"/news/sources/{delete_id}").status_code == 200

    restored = client.post("/news/sources/restore-defaults")
    assert restored.status_code == 200
    body = restored.json()
    assert body["restored"] >= 1
    assert len(body["sources"]) == 4
    assert any(s["url"] == listed["sources"][0]["url"] for s in body["sources"])
    assert any(s["url"] == "https://example.com/my-feed.xml" for s in body["sources"])
    assert sum(1 for s in body["sources"] if s["is_preset"]) == 3
