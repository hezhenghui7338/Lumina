"""E2E-BOOT-01: Startup API JSON contract for Swift CoreClient decoding."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pydantic import ValidationError

from lumina_core.api.routes import (
    ResegmentRequest,
    _prioritize_summarize_activity,
    apply_book_list_filter,
    book_public_dict,
)
from lumina_core.config import Settings
from lumina_core.db.repos import BookRepo, SegmentRepo
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


def test_book_chat_scope_requires_ready_index(client):
    book_id = _import_sample(client)
    client.post(f"/books/{book_id}/summarize/stop")
    book = client.get(f"/books/{book_id}").json()
    if book.get("index_status") == "ready":
        return
    resp = client.post(
        f"/books/{book_id}/chat",
        json={"message": "全书？", "segment_index": 0, "scope": "book"},
    )
    assert resp.status_code == 409
    assert "索引" in (resp.json().get("detail") or "")


def test_books_list_summary_progress_matches_get(client):
    """GET /books must return live summary_ready_count (library progress bar)."""
    book_id = _import_sample(client)
    client.post(f"/books/{book_id}/summarize/stop")

    conn = client.app.state.lumina.conn  # type: ignore[attr-defined]
    seg = SegmentRepo(conn).get_by_index(book_id, 0)
    assert seg is not None
    SegmentRepo(conn).set_status(seg["id"], "ready")
    segment_total = len(SegmentRepo(conn).list_for_book(book_id, include_body=False))

    detail = client.get(f"/books/{book_id}").json()
    listed = next(b for b in client.get("/books").json()["books"] if b["id"] == book_id)

    assert detail["summary_ready_count"] == 1
    assert detail["summary_total_count"] == segment_total
    assert listed["summary_ready_count"] == detail["summary_ready_count"]
    assert listed["summary_total_count"] == detail["summary_total_count"]

    patched = client.patch(f"/books/{book_id}", json={"is_favorite": True}).json()
    assert patched["summary_ready_count"] == detail["summary_ready_count"]
    assert patched["summary_total_count"] == detail["summary_total_count"]


def test_books_list_includes_summarize_state(client):
    book_id = _import_sample(client)
    client.post(f"/books/{book_id}/summarize/stop")

    listed = next(b for b in client.get("/books").json()["books"] if b["id"] == book_id)
    assert listed["summarize_state"] == "paused"
    assert isinstance(listed["summarize_queued_count"], int)

    overview = client.get("/books/summarize/overview").json()
    assert isinstance(overview["counts"], dict)
    assert "paused" in overview["counts"]
    assert isinstance(overview["user_paused_all"], bool)


def test_prioritize_summarize_activity_orders_running_then_queued():
    books = [
        {"id": "idle", "summarize_state": "idle"},
        {"id": "running", "summarize_state": "running"},
        {"id": "recent", "last_opened_at": "2024-05-01T00:00:00+00:00"},
        {"id": "queued", "summarize_state": "queued"},
    ]

    result = _prioritize_summarize_activity(books)

    assert [b["id"] for b in result] == ["running", "queued", "idle", "recent"]


def test_apply_book_list_filter_summarizing_and_idle():
    books = [
        {"id": "idle", "summarize_state": "idle"},
        {"id": "paused", "summarize_state": "paused"},
        {"id": "running", "summarize_state": "running"},
        {"id": "queued", "summarize_state": "queued"},
        {"id": "done", "summarize_state": "summarized"},
        {"id": "chunking", "summarize_state": "segmenting", "status": "processing"},
        {"id": "fail", "status": "error", "summarize_state": "summarized"},
        {"id": "cancel", "status": "error", "summarize_state": "idle"},
        {
            "id": "hole",
            "status": "unread",
            "summarize_state": "summarized",
            "segment_count": 0,
        },
    ]
    summarizing = apply_book_list_filter(books, "summarizing")
    idle = apply_book_list_filter(books, "idle")
    segmenting = apply_book_list_filter(books, "segmenting")
    failed = apply_book_list_filter(books, "error")
    assert [b["id"] for b in summarizing] == ["running", "queued"]
    assert [b["id"] for b in idle] == ["idle", "paused"]
    assert [b["id"] for b in segmenting] == ["chunking", "hole"]
    assert [b["id"] for b in failed] == ["fail", "cancel"]
    assert apply_book_list_filter(books, "all") == books


def test_book_public_dict_processing_is_segmenting():
    """Import/resegment must not look summarized while segment_count is still 0."""
    row = {
        "id": "b1",
        "title": "Importing",
        "status": "processing",
        "segment_count": 0,
        "is_favorite": 0,
    }
    out = book_public_dict(row, summarize_state="summarized")
    assert out["summarize_state"] == "segmenting"
    assert out["summarize_queued_count"] == 0


def test_book_public_dict_empty_unread_is_segmenting_not_summarized():
    """0-segment unread must not occupy 已摘要 — that hid new imports."""
    row = {
        "id": "b1",
        "title": "Stuck",
        "status": "unread",
        "segment_count": 0,
        "is_favorite": 0,
    }
    out = book_public_dict(row, summarize_state="summarized")
    assert out["summarize_state"] == "segmenting"
    assert out["status"] == "unread"


def test_list_books_repairs_empty_unread_to_ingest_failed(client):
    conn = client.app.state.lumina.conn
    book_id = BookRepo(conn).insert(
        title="Orphan",
        format="txt",
        file_path="/tmp/orphan.txt",
        segment_count=0,
        status="unread",
    )["id"]

    listed = next(b for b in client.get("/books").json()["books"] if b["id"] == book_id)
    assert listed["status"] == "error"
    assert listed["ingest_error"] == "导入中断"

    failed_ids = [
        b["id"]
        for b in client.get("/books", params={"filter": "error"}).json()["books"]
    ]
    idle_ids = [
        b["id"] for b in client.get("/books", params={"filter": "idle"}).json()["books"]
    ]
    segmenting_ids = [
        b["id"]
        for b in client.get("/books", params={"filter": "segmenting"}).json()["books"]
    ]
    summarized_ids = [
        b["id"]
        for b in client.get("/books", params={"filter": "summarized"}).json()["books"]
    ]
    assert book_id in failed_ids
    assert book_id not in idle_ids
    assert book_id not in segmenting_ids
    assert book_id not in summarized_ids


def test_list_books_recent_prioritizes_summarize_activity(client):
    book_running = import_sample_book(client, sample_name="sample.txt")
    book_queued = import_sample_book(client, sample_name="chunk_classical.txt")
    book_idle = import_sample_book(client, sample_name="chunk_long_novel.txt")

    BookRepo(client.app.state.lumina.conn).update(
        book_idle,
        last_opened_at="2024-05-01T00:00:00+00:00",
    )

    queue = client.app.state.lumina.job_queue
    original = queue.summarize_state_for_book

    def fake_state(book_id, *, ready, total):
        if book_id == book_running:
            return "running"
        if book_id == book_queued:
            return "queued"
        return original(book_id, ready=ready, total=total)

    queue.summarize_state_for_book = fake_state

    ids = [b["id"] for b in client.get("/books", params={"sort": "recent"}).json()["books"]]
    assert ids[:2] == [book_running, book_queued]
    assert ids.index(book_running) < ids.index(book_idle)
    assert ids.index(book_queued) < ids.index(book_idle)

    conn = client.app.state.lumina.conn
    repo_title_ids = [b["id"] for b in BookRepo(conn).list_books(sort="title")]
    api_title_ids = [
        b["id"] for b in client.get("/books", params={"sort": "title"}).json()["books"]
    ]
    assert api_title_ids == repo_title_ids


def test_list_books_filter_summarizing_uses_queue_state(client):
    book_running = import_sample_book(client, sample_name="sample.txt")
    book_idle = import_sample_book(client, sample_name="chunk_classical.txt")

    queue = client.app.state.lumina.job_queue
    original = queue.summarize_state_for_book

    def fake_state(book_id, *, ready, total):
        if book_id == book_running:
            return "running"
        if book_id == book_idle:
            return "idle"
        return original(book_id, ready=ready, total=total)

    queue.summarize_state_for_book = fake_state

    summarizing_ids = [
        b["id"]
        for b in client.get("/books", params={"filter": "summarizing"}).json()["books"]
    ]
    idle_ids = [
        b["id"] for b in client.get("/books", params={"filter": "idle"}).json()["books"]
    ]
    assert summarizing_ids == [book_running]
    assert book_idle in idle_ids
    assert book_running not in idle_ids


def test_processing_book_is_segmenting_state(client):
    book_id = import_sample_book(client, sample_name="sample.txt")
    BookRepo(client.app.state.lumina.conn).update(book_id, status="processing")

    listed = next(b for b in client.get("/books").json()["books"] if b["id"] == book_id)
    assert listed["summarize_state"] == "segmenting"
    assert listed["status"] == "processing"

    segmenting_ids = [
        b["id"]
        for b in client.get("/books", params={"filter": "segmenting"}).json()["books"]
    ]
    idle_ids = [
        b["id"] for b in client.get("/books", params={"filter": "idle"}).json()["books"]
    ]
    summarizing_ids = [
        b["id"]
        for b in client.get("/books", params={"filter": "summarizing"}).json()["books"]
    ]
    summarized_ids = [
        b["id"]
        for b in client.get("/books", params={"filter": "summarized"}).json()["books"]
    ]
    assert book_id in segmenting_ids
    assert book_id not in idle_ids
    assert book_id not in summarizing_ids
    assert book_id not in summarized_ids

    detail = client.get(f"/books/{book_id}").json()
    assert detail["summarize_state"] == "segmenting"
    assert client.get("/books/summarize/overview").json()["counts"]["segmenting"] >= 1


def test_summarize_batch_start_stop(client):
    book_id = _import_sample(client)
    client.post(f"/books/{book_id}/summarize/stop")

    stop = client.post("/books/summarize/stop", json={"book_ids": [book_id]})
    assert stop.status_code == 200
    body = stop.json()
    assert body["scope"] == "batch"
    assert book_id in body["book_ids"]

    start = client.post(
        "/books/summarize/start",
        json={"book_ids": [book_id], "summary_tier": "advanced"},
    )
    assert start.status_code == 200
    assert start.json()["scope"] == "batch"
    assert start.json()["summary_tier"] == "advanced"

    missing = client.post(
        "/books/summarize/stop",
        json={"book_ids": [book_id, "nonexistent-id"]},
    )
    assert missing.status_code == 200
    assert "nonexistent-id" in missing.json()["skipped"]

    # Drain work before TestClient lifespan shutdown so teardown cannot hang.
    drained = client.post("/books/summarize/stop", json={"book_ids": [book_id]})
    assert drained.status_code == 200


def test_summarize_overview_exposes_indexing_and_stall_reason(client):
    """The chip needs a reason whenever work is queued but nothing runs."""
    _import_sample(client)
    body = client.get("/books/summarize/overview").json()
    counts = body["counts"]
    assert isinstance(counts["indexing"], int)
    assert isinstance(body["indexing_queued"], int)
    assert "stalled_reason" in body
    if counts["queued"] > 0 and counts["running"] == 0:
        assert body["stalled_reason"], "queued work with nothing running needs a reason"


def test_build_book_index_requires_complete_summaries(client):
    """Whole-book index is opt-in and only valid once every segment is ready."""
    book_id = _import_sample(client)
    client.post(f"/books/{book_id}/summarize/stop")

    too_early = client.post(f"/books/{book_id}/index")
    assert too_early.status_code == 409

    missing = client.post("/books/nonexistent-id/index")
    assert missing.status_code == 404


def test_put_settings_rejects_invalid_prompts(client):
    body = client.get("/settings").json()
    prompts = body["prompts"]
    prompts["segment"] = "missing placeholders"
    resp = client.put("/settings", json={"prompts": prompts})
    assert resp.status_code == 422


def test_settings_matches_swift_app_settings(client):
    """GET /settings shape matches Swift AppSettings / resource pool."""
    body = client.get("/settings").json()
    assert isinstance(body["target_language"], str)
    assert isinstance(body["web_search_provider"], str)
    assert body.get("web_search_enabled") is True
    assert isinstance(body["ocr_cloud_base_url"], str)
    assert isinstance(body["ocr_cloud_model"], str)
    assert body["ocr_cloud_api_key"] is None
    assert isinstance(body["ocr_cloud_timeout_seconds"], (int, float))
    assert body.get("debug_mode") is False
    assert body.get("auto_start_summary") is False
    assert body.get("default_segment_tier") == "normal"
    prompts = body["prompts"]
    assert isinstance(prompts["segment"], str)
    assert isinstance(prompts["document"], str)
    assert isinstance(prompts["chat"], str)
    assert isinstance(prompts["news_chat"], str)
    assert isinstance(prompts["translate"], str)
    assert isinstance(prompts["classify"], str)
    assert isinstance(prompts.get("rollup"), (str, type(None)))
    if prompts.get("rollup"):
        assert "{text}" in prompts["rollup"]
    defaults = body["prompts_defaults"]
    assert isinstance(defaults["segment"], str)
    assert defaults["segment"] == prompts["segment"]
    models = body["models"]
    assert isinstance(models["resources"], list)
    for resource in models["resources"]:
        assert isinstance(resource["id"], str)
        assert isinstance(resource["provider"], str)
        assert isinstance(resource["model"], str)
        assert resource["advanced_model"] is None or isinstance(
            resource["advanced_model"], str
        )
    for profile in ("chat", "summarize"):
        route = models[profile]
        assert isinstance(route["priority"], list)
        assert all(isinstance(item, str) for item in route["priority"])


def test_settings_redacts_and_preserves_ocr_cloud_key(client):
    first = client.put(
        "/settings",
        json={
            "ocr_cloud_base_url": "https://example.test/v1",
            "ocr_cloud_model": "vision-model",
            "ocr_cloud_api_key": "ocr-secret",
        },
    )
    assert first.status_code == 200
    assert first.json()["ocr_cloud_api_key"] == "***"

    second = client.put(
        "/settings",
        json={
            "ocr_cloud_model": "vision-model-v2",
            "ocr_cloud_api_key": "***",
        },
    )
    assert second.status_code == 200
    assert second.json()["ocr_cloud_api_key"] == "***"
    assert second.json()["ocr_cloud_model"] == "vision-model-v2"


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


def test_resegment_request_allows_min_target_200():
    assert ResegmentRequest(chunk_target_chars=200).chunk_target_chars == 200
    assert ResegmentRequest(chunk_target_chars=200).segment_tier == "normal"
    assert (
        ResegmentRequest(chunk_target_chars=200, segment_tier="advanced").segment_tier
        == "advanced"
    )
    with pytest.raises(ValidationError):
        ResegmentRequest(chunk_target_chars=199)
    with pytest.raises(ValidationError):
        ResegmentRequest(chunk_target_chars=8001)


def test_book_public_dict_exposes_ingest_error():
    row = {
        "id": "b1",
        "title": "金阁寺",
        "status": "error",
        "is_favorite": 0,
        "segment_count": 0,
        "metadata_json": json.dumps({"ingest_error": "unknown encoding: utf-8-sig"}),
    }
    out = book_public_dict(row)
    assert out["ingest_error"] == "unknown encoding: utf-8-sig"
    assert "metadata_json" not in out
    assert "document_tree" not in out


def test_books_list_omits_metadata_json_and_document_tree(client):
    book_id = import_sample_book(client)
    listed = next(b for b in client.get("/books").json()["books"] if b["id"] == book_id)
    assert "metadata_json" not in listed
    assert "document_tree" not in listed
    detail = client.get(f"/books/{book_id}").json()
    assert "metadata_json" not in detail
    assert "document_tree" not in detail
    conn = client.app.state.lumina.conn
    stored = json.loads(BookRepo(conn).get(book_id)["metadata_json"] or "{}")
    assert "document_tree" not in stored


def test_drop_stored_document_trees_strips_legacy_blob(client):
    conn = client.app.state.lumina.conn
    book_id = import_sample_book(client)
    repo = BookRepo(conn)
    meta = json.loads(repo.get(book_id)["metadata_json"] or "{}")
    meta["document_tree"] = {"kind": "book", "children": [{"title": "x"} for _ in range(50)]}
    repo.update(book_id, metadata_json=meta)
    assert "document_tree" in json.loads(repo.get(book_id)["metadata_json"])
    listed = next(b for b in client.get("/books").json()["books"] if b["id"] == book_id)
    assert "metadata_json" not in listed
    assert "document_tree" not in json.loads(repo.get(book_id)["metadata_json"])


def test_segment_detail_bullet_labels_is_json_array(client):
    """GET .../segments/{idx} must emit bullet_labels as array for Swift SegmentRow."""
    book_id = import_sample_book(client)
    conn = client.app.state.lumina.conn  # type: ignore[attr-defined]
    seg = SegmentRepo(conn).get_by_index(book_id, 0)
    assert seg is not None
    # Simulate legacy/cached TEXT column (JSON array stored as a string).
    with conn:
        conn.execute(
            "UPDATE segments SET bullet_labels = ?, summary_preview = ? WHERE id = ?",
            ('["邻里"]', "本段交代邻里。", seg["id"]),
        )
    detail = client.get(f"/books/{book_id}/segments/0").json()
    assert isinstance(detail.get("raw_text"), str)
    assert detail["bullet_labels"] == ["邻里"]
    assert not isinstance(detail["bullet_labels"], str)
