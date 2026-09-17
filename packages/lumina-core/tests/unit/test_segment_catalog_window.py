"""Progressive segment catalog: open path must stay O(window), not O(n)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumina_core.config import Settings
from lumina_core.db.repos import CATALOG_WINDOW_DEFAULT, SegmentRepo
from lumina_core.db.schema import init_db
from lumina_core.main import create_app
from lumina_core.models.router import set_router
from tests.support.mock_router import MockModelRouter


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMINA_DATA_DIR", str(tmp_path))
    router = MockModelRouter()
    app = create_app(Settings(data_dir=tmp_path))
    app.state.lumina.router = router
    app.state.lumina.job_queue.router = router
    set_router(router)
    with TestClient(app) as c:
        yield c


def _seed_segments(conn, book_id: str, n: int) -> None:
    conn.execute(
        "INSERT INTO books (id, title, format, file_path, created_at, updated_at, "
        "segment_count, summary_total_count, summary_ready_count) "
        "VALUES (?, 'big', 'txt', '/x', 'now', 'now', ?, ?, 0)",
        (book_id, n, n),
    )
    rows = [
        {
            "id": f"{book_id}-{i}",
            "book_id": book_id,
            "idx": i,
            "chapter": f"§第{i}章",
            "page_range": None,
            "anchor_label": f"a{i}",
            "raw_text": f"正文{i}",
            "summary_status": "pending",
            "retry_count": 0,
        }
        for i in range(n)
    ]
    SegmentRepo(conn).insert_many(rows)


def test_list_catalog_page_around_is_bounded(tmp_path: Path) -> None:
    conn = init_db(tmp_path / "window.db")
    _seed_segments(conn, "big", 5000)
    page = SegmentRepo(conn).list_catalog_page("big", around=2500, limit=64)
    assert page["total"] == 5000
    assert len(page["segments"]) == 64
    idxs = [s["idx"] for s in page["segments"]]
    assert idxs == list(range(idxs[0], idxs[0] + 64))
    assert 2500 in idxs
    assert page["has_more_before"] is True
    assert page["has_more_after"] is True
    head = SegmentRepo(conn).list_catalog_page("big", around=0, limit=64)
    assert [s["idx"] for s in head["segments"]] == list(range(64))
    assert head["has_more_before"] is False
    assert head["has_more_after"] is True


def test_list_catalog_page_after_before(tmp_path: Path) -> None:
    conn = init_db(tmp_path / "page.db")
    _seed_segments(conn, "p", 100)
    after = SegmentRepo(conn).list_catalog_page("p", after_idx=40, limit=10)
    assert [s["idx"] for s in after["segments"]] == list(range(41, 51))
    assert after["has_more_before"] is True
    assert after["has_more_after"] is True
    before = SegmentRepo(conn).list_catalog_page("p", before_idx=40, limit=10)
    assert [s["idx"] for s in before["segments"]] == list(range(30, 40))
    assert before["has_more_before"] is True
    assert before["has_more_after"] is True
    tail = SegmentRepo(conn).list_catalog_page("p", after_idx=95, limit=10)
    assert [s["idx"] for s in tail["segments"]] == list(range(96, 100))
    assert tail["has_more_after"] is False


def test_segments_api_window_and_compat_full(client) -> None:
    conn = client.app.state.lumina.conn
    _seed_segments(conn, "api-big", 300)

    window = client.get(
        "/books/api-big/segments",
        params={"around": 150, "limit": 32},
    )
    assert window.status_code == 200
    body = window.json()
    assert body["total"] == 300
    assert len(body["segments"]) == 32
    assert body["has_more_before"] is True
    assert body["has_more_after"] is True
    assert "raw_text" not in body["segments"][0]
    assert "summary_json" not in body["segments"][0]

    after = client.get(
        "/books/api-big/segments",
        params={"after_idx": 200, "limit": 20},
    ).json()
    assert [s["idx"] for s in after["segments"]] == list(range(201, 221))

    full = client.get("/books/api-big/segments").json()
    assert full["total"] == 300
    assert len(full["segments"]) == 300
    assert full["has_more_before"] is False
    assert full["has_more_after"] is False


def test_book_events_snapshot_is_progress_only() -> None:
    """SSE connect must not dump O(n) segment rows (handshake lock)."""
    routes = Path(__file__).resolve().parents[2] / "lumina_core" / "api" / "routes.py"
    text = routes.read_text(encoding="utf-8")
    start = text.index("async def book_events")
    chunk = text[start : start + 1200]
    assert '"type": "snapshot"' in chunk
    assert "summary_ready_count" in chunk
    assert "summary_total_count" in chunk
    assert "list_for_book" not in chunk
    assert "list_catalog" not in chunk


def test_reader_open_uses_compat_full_catalog() -> None:
    """macOS reader open intentionally pulls compat full slim catalog (d383158).

    Backend around/after_idx/before_idx APIs remain; the client open path does
    not pass around/limit (product rollback — large books may hitch).
    """
    root = Path(__file__).resolve().parents[4]
    reader = root / "apps" / "macos" / "Lumina" / "Features" / "Reader" / "ReaderView.swift"
    text = reader.read_text(encoding="utf-8")
    assert "openCatalogWindowLimit" not in text
    assert "fillCatalogInBackground" not in text
    load_start = text.index("func load(")
    next_fn = text.find("\n    func ", load_start + 1)
    load_chunk = text[load_start : next_fn if next_fn != -1 else load_start + 12000]
    first_list = load_chunk.index("listSegments(")
    open_list = load_chunk[first_list : first_list + 200]
    assert "async let listTask = core.listSegments(bookId: bookId)" in load_chunk
    assert "around:" not in open_list
    assert "page.segments" in load_chunk


def test_reader_feed_uses_full_foreach() -> None:
    """macOS main feed is full ForEach(segments) after d383158 rollback."""
    root = Path(__file__).resolve().parents[4]
    reader = root / "apps" / "macos" / "Lumina" / "Features" / "Reader" / "ReaderView.swift"
    models = (
        root
        / "apps"
        / "macos"
        / "Lumina"
        / "Features"
        / "Reader"
        / "SegmentSidebarModels.swift"
    )
    reader_text = reader.read_text(encoding="utf-8")
    models_text = models.read_text(encoding="utf-8")
    assert "ForEach(viewModel.segments" in reader_text
    assert "SegmentRenderWindow.readingWindow" not in reader_text
    assert "readRenderBuffer" not in models_text
    # Sidebar still has slice() for catalog overlay windowing.
    assert "static func slice<" in models_text
    feed_start = reader_text.index("private var segmentContent")
    feed_end = reader_text.index("\n    private func toggleSource", feed_start)
    feed_chunk = reader_text[feed_start:feed_end]
    assert "ForEach(viewModel.segments, id: \\.idx)" in feed_chunk
    assert "readingFeed(window:" not in feed_chunk


def test_default_window_constant() -> None:
    assert CATALOG_WINDOW_DEFAULT == 64
