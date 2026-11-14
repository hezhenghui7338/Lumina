"""Library management API e2e tests."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumina_core.config import Settings
from lumina_core.db.repos import BookRepo
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


def test_trash_read_restore_and_permanent_delete(client, monkeypatch):
    state = client.app.state.lumina
    state.job_queue.auto_start_summary = True
    book_id = _import_sample(client)
    segment = client.get(f"/books/{book_id}/segments").json()["segments"][0]
    note = client.post("/notes", json={
        "book_id": book_id, "segment_id": segment["id"], "content": "Keep this note",
    })
    assert note.status_code == 200
    before = client.get(f"/books/{book_id}").json()
    response = client.post(f"/books/{book_id}/trash")
    assert response.status_code == 200
    assert response.json()["trashed_at"]
    assert client.post(f"/books/{book_id}/trash").json()["trashed_at"] == response.json()["trashed_at"]
    assert client.get("/books").json()["books"] == []
    assert client.get("/notes").json()["notes"] == []
    assert client.get("/library/tags").status_code == 200
    assert [b["id"] for b in client.get("/books?visibility=trash").json()["books"]] == [book_id]
    assert client.get("/books?visibility=all").status_code == 422

    # Explicit reading works without reviving jobs or visibility.
    def unexpected(*args, **kwargs):
        pytest.fail("Reading trash must not start automatic AI work")
    monkeypatch.setattr(state.job_queue, "schedule_intro", unexpected)
    monkeypatch.setattr(state.job_queue, "enqueue_book_prefetch", unexpected)
    assert client.post(f"/books/{book_id}/open").status_code == 200
    assert client.get(f"/books/{book_id}/segments/0").status_code == 200
    assert client.get("/notes", params={"book_id": book_id}).json()["notes"][0]["content"] == "Keep this note"
    assert client.patch(f"/books/{book_id}/reading-progress", json={"segment_index": 0}).status_code == 200
    assert client.get("/books").json()["books"] == []
    for action in ("summarize/start", "index", "intro/generate", "summarize/regenerate", "segments/0/retry"):
        assert client.post(f"/books/{book_id}/{action}").status_code == 409

    restored = client.post(f"/books/{book_id}/restore")
    assert restored.status_code == 200
    assert restored.json()["trashed_at"] is None
    assert restored.json()["summarize_intent"] == "paused"
    assert restored.json()["segment_count"] == before["segment_count"]
    assert len(client.get("/books").json()["books"]) == 1
    assert len(client.get("/notes").json()["notes"]) == 1
    assert client.delete(f"/books/{book_id}?only_trashed=true").status_code == 409
    assert client.post(f"/books/{book_id}/restore").status_code == 200
    assert client.post(f"/books/{book_id}/trash").status_code == 200
    assert client.delete(f"/books/{book_id}?only_trashed=true").status_code == 200
    assert client.get(f"/books/{book_id}").status_code == 404
    assert client.get("/books?visibility=trash").json()["books"] == []
    assert not (state.books_dir / book_id).exists()
    assert client.post("/books/missing/trash").status_code == 404
    assert client.post("/books/missing/restore").status_code == 404


@pytest.mark.parametrize("overwrite", [False, True])
@pytest.mark.parametrize("kind", ["file", "paste", "url"])
def test_reimport_trash_always_skips_without_replacing_data(client, overwrite, kind):
    from lumina_core.ingest.loader import file_hash
    from lumina_core.ingest.paste import prepare_pasted_text
    from lumina_core.ingest.web import url_import_hash

    state = client.app.state.lumina
    sample = BOOK_FIXTURES / "sample.txt"
    text = "Book title\nThis is the original pasted book content."
    url = "https://example.com/reading"
    digest = {"file": lambda: file_hash(sample), "paste": lambda: prepare_pasted_text(text).digest,
              "url": lambda: url_import_hash(url)}[kind]()
    repo = BookRepo(state.conn)
    book = repo.insert(title="Keep me hidden", format="txt", file_path=str(sample), file_hash=digest)
    repo.set_trashed(book["id"], True)
    before = repo.get(book["id"])
    path, body = {
        "file": ("/books/import", {"paths": [str(sample)]}),
        "paste": ("/books/import-paste", {"text": text}),
        "url": ("/books/import-url", {"url": url}),
    }[kind]
    response = client.post(path, json={**body, "overwrite": overwrite})
    assert response.status_code == 409
    assert response.json()["detail"]["trashed_at"] == before["trashed_at"]
    assert repo.get(book["id"]) == before
    assert len(repo.list_books(visibility="all")) == 1


@pytest.mark.parametrize("kind", ["import", "resegment"])
def test_trash_cancels_queued_processing_without_waiting_for_other_books(client, kind):
    state = client.app.state.lumina
    if kind == "resegment":
        book_id = _import_sample(client)
        before = client.get(f"/books/{book_id}/segments").json()["segments"]
    client.portal.call(state.cpu_job_lock.acquire)
    try:
        if kind == "import":
            book_id = import_sample_book(client, wait=False)
        else:
            assert client.post(f"/books/{book_id}/resegment", json={"chunk_target_chars": 4000}).status_code == 202
        started = time.monotonic()
        response = client.post(f"/books/{book_id}/trash")
        assert response.status_code == 200
        assert time.monotonic() - started < 3
        assert state.cpu_job_lock.locked(), "Trash must not release another book's CPU lock"
        assert response.json()["status"] != "processing"
        if kind == "resegment":
            assert client.get(f"/books/{book_id}/segments").json()["segments"] == before
    finally:
        client.portal.call(state.cpu_job_lock.release)


def test_list_books_filter_and_patch_favorite(client):
    book_id = _import_sample(client)
    client.post(f"/books/{book_id}/open")

    all_books = client.get("/books", params={"filter": "all"}).json()["books"]
    assert any(b["id"] == book_id for b in all_books)

    patched = client.patch(
        f"/books/{book_id}",
        json={"is_favorite": True, "title": "新标题"},
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["is_favorite"] is True
    assert body["title"] == "新标题"
    stored = BookRepo(client.app.state.lumina.conn).get(book_id)
    assert json.loads(stored["metadata_json"]).get("title_user_set") is True

    favorites = client.get("/books", params={"sort": "favorite"}).json()["books"]
    assert favorites[0]["id"] == book_id


def test_ask_library_open_count_and_tag_changes_reach_bookshelf(client):
    book_id = _import_sample(client)
    client.post(f"/books/{book_id}/open")
    result = client.post("/library/ask", json={"message": "我有多少本书？"})
    assert result.status_code == 200
    row = next(b for b in result.json()["books"] if b["id"] == book_id)
    assert row["open_count"] == 1
    preview = client.post(
        f"/library/results/{result.json()['result_id']}/preview-tag",
        json={"name": "待读"},
    )
    assert preview.status_code == 200
    assert client.post(f"/library/results/{preview.json()['result_id']}/apply").status_code == 200
    books = client.get("/books").json()["books"]
    assert next(b for b in books if b["id"] == book_id)["tags"] == ["待读"]
    tag = client.get("/library/tags").json()["tags"][0]
    assert client.patch(f"/library/tags/{tag['id']}", json={"name": "最近想读"}).status_code == 200
    books = client.get("/books").json()["books"]
    assert next(b for b in books if b["id"] == book_id)["tags"] == ["最近想读"]


def test_patch_book_rejects_empty_title(client):
    book_id = _import_sample(client)
    before = client.get(f"/books/{book_id}").json()["title"]
    resp = client.patch(f"/books/{book_id}", json={"title": "   "})
    assert resp.status_code == 400
    assert client.get(f"/books/{book_id}").json()["title"] == before


def test_list_books_filter_unread_reading_finished(client):
    book_id = _import_sample(client)
    unread = client.get("/books", params={"filter": "unread"}).json()["books"]
    assert any(b["id"] == book_id for b in unread)

    client.post(f"/books/{book_id}/open")
    reading = client.get("/books", params={"filter": "reading"}).json()["books"]
    assert any(b["id"] == book_id for b in reading)
    unread_after = client.get("/books", params={"filter": "unread"}).json()["books"]
    assert not any(b["id"] == book_id for b in unread_after)

    long_id = import_sample_book(client, sample_name="chunk_long_novel.txt")
    client.post(f"/books/{long_id}/open")
    book = client.get(f"/books/{long_id}").json()
    last_idx = max(int(book.get("segment_count") or 1) - 1, 0)
    patched = client.patch(
        f"/books/{long_id}/reading-progress",
        json={"segment_index": last_idx},
    )
    assert patched.status_code == 200
    finished = client.get("/books", params={"filter": "finished"}).json()["books"]
    assert any(b["id"] == long_id for b in finished)


def test_list_books_filter_by_category(client):
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

    literature = client.get("/books", params={"filter": "文学"}).json()["books"]
    assert any(b["id"] == book_id for b in literature)

    history = client.get("/books", params={"filter": "历史"}).json()["books"]
    assert not any(b["id"] == book_id for b in history)


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

    summarized = client.get("/books", params={"filter": "summarized"}).json()["books"]
    assert any(b["id"] == book_id for b in summarized)


def test_reader_bootstrap_flow(client):
    """ReaderView.load: fetchBook + settings + openBook + windowed listSegments."""
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
    opened = open_resp.json()
    assert opened["status"] == "opened"
    resume = int(opened.get("current_segment_index") or 0)

    seg_resp = client.get(
        f"/books/{book_id}/segments",
        params={"around": resume, "limit": 64},
    )
    assert seg_resp.status_code == 200
    body = seg_resp.json()
    segments = body["segments"]
    assert segments
    assert body["total"] >= len(segments)
    first = segments[0]
    assert "raw_text" not in first
    assert "translation" not in first
    assert "char_count" in first
    assert "summary_provider" in first
    assert "summary_model" in first
    assert "summary_json" not in first
