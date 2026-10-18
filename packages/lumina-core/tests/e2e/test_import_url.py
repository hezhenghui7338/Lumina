"""URL import becomes an offline book without blocking the request."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumina_core.config import Settings
from lumina_core.ingest.web import WebImportError, WebPage
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


def test_import_url_returns_before_download_and_keeps_text(client, tmp_path, monkeypatch):
    release = threading.Event()

    def fake(url: str) -> WebPage:
        # If the request awaited this download, it would sit here until the
        # timeout and the book would be marked failed before the test continues.
        if not release.wait(3):
            raise WebImportError("下载仍被请求堵住")
        return WebPage(
            final_url=url,
            title="网页标题",
            text="这是从网页抽出来的正文，应当进入分段。",
        )

    monkeypatch.setattr("lumina_core.api.routes.fetch_web_page", fake)
    resp = client.post("/books/import-url", json={"url": "https://Example.com/post/"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "processing"
    release.set()
    book_id = body["book_id"]
    finished = wait_for_ingest(client, book_id)
    assert finished["status"] in ("unread", "reading", "summarized")
    assert finished["title"] == "网页标题"
    import sqlite3

    row = sqlite3.connect(tmp_path / "lumina.db").execute(
        "SELECT metadata_json FROM books WHERE id = ?", (book_id,)
    ).fetchone()
    assert row and "https://example.com/post" in row[0]
    segment = client.get(f"/books/{book_id}/segments/0").json()
    assert "网页抽出来的正文" in (segment.get("raw_text") or "")


def test_import_url_duplicate_is_conflict_until_overwrite(client, monkeypatch):
    monkeypatch.setattr(
        "lumina_core.api.routes.fetch_web_page",
        lambda url: WebPage(final_url=url, title="同一篇", text="重复导入用的正文。"),
    )
    first = client.post("/books/import-url", json={"url": "https://example.com/same#top"})
    assert first.status_code == 200
    again = client.post("/books/import-url", json={"url": "https://example.com/same/"})
    assert again.status_code == 409
    assert again.json()["detail"]["existing_book_id"] == first.json()["book_id"]
    overwritten = client.post(
        "/books/import-url",
        json={"url": "https://example.com/same", "overwrite": True},
    )
    assert overwritten.status_code == 200
    assert overwritten.json()["book_id"] != first.json()["book_id"]


def test_import_url_extract_failure_marks_book_error(client, monkeypatch):
    def boom(url: str) -> WebPage:
        raise WebImportError("未能抽取正文")

    monkeypatch.setattr("lumina_core.api.routes.fetch_web_page", boom)
    resp = client.post("/books/import-url", json={"url": "https://example.com/empty"})
    assert resp.status_code == 200
    book = wait_for_ingest(client, resp.json()["book_id"])
    assert book["status"] == "error"
    assert book.get("ingest_error") == "未能抽取正文"


def test_import_url_rejects_non_http(client):
    resp = client.post("/books/import-url", json={"url": "ftp://example.com/a"})
    assert resp.status_code == 400
    assert client.get("/books").json()["books"] == []
