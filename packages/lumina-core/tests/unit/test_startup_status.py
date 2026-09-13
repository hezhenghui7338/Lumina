"""Unit tests for /startup/status cache progress and detail reporting."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lumina_core.config import Settings
from lumina_core.db.repos import BookRepo
from lumina_core.main import create_app
from lumina_core.models.router import set_router
from tests.support.mock_router import MockModelRouter


@pytest.fixture
def test_setup(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMINA_DATA_DIR", str(tmp_path))
    settings = Settings(data_dir=tmp_path)
    router = MockModelRouter(responses={})
    app = create_app(settings)
    app.state.lumina.router = router
    app.state.lumina.job_queue.router = router
    set_router(router)
    return app, settings, tmp_path


def test_startup_status_schema(test_setup):
    app, _, _ = test_setup
    with TestClient(app) as client:
        resp = client.get("/startup/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["engine"] == "ready"
        assert data["data"] in ("pending", "running", "done")
        assert data["cache"] in ("pending", "running", "done")
        assert "cache_progress" in data
        assert "cache_detail" in data
        assert data["news"] in ("pending", "running", "done", "failed")
        assert "news_detail" in data


def test_startup_news_running_while_cache_done(test_setup):
    """Boot news must not block product-ready: cache can be done while news runs."""
    app, _, _ = test_setup
    state = app.state.lumina
    state.job_queue._startup_data_phase = "done"
    state.job_queue._startup_cache_phase = "done"
    state.startup_news_phase = "running"
    status = state.startup_status()
    assert status["data"] == "done"
    assert status["cache"] == "done"
    assert status["news"] == "running"

async def test_startup_cache_progress_multi_books(test_setup):
    app, _, _ = test_setup
    repo = BookRepo(app.state.lumina.conn)

    # Insert 3 books
    for i in range(1, 4):
        repo.insert(
            id=f"book-{i}",
            title=f"Book {i}",
            format="txt",
            file_path=f"/path/{i}.txt",
        )

    observed_progress: list[tuple[float | None, str | None]] = []

    queue = app.state.lumina.job_queue
    original_set_progress = queue.set_cache_progress

    def recording_set_progress(progress: float | None, detail: str | None) -> None:
        observed_progress.append((progress, detail))
        original_set_progress(progress, detail)

    queue.set_cache_progress = recording_set_progress

    # Run the deferred startup work
    await queue._deferred_startup_work()

    details = [d for _, d in observed_progress if d is not None]
    assert any("清理目录" in d for d in details)
    assert any("校准目录" in d for d in details)
    assert any("校准章节" in d for d in details)
    assert any("恢复书籍状态 (1/3)" in d for d in details)
    assert any("恢复书籍状态 (2/3)" in d for d in details)
    assert any("恢复书籍状态 (3/3)" in d for d in details)

    progs = [p for p, _ in observed_progress if p is not None]
    assert len(progs) >= 6
    assert progs[-1] == 1.0
    for a, b in zip(progs, progs[1:]):
        assert b >= a

    # Finally status endpoint reports done, 1.0 progress, and detail cleared
    status = app.state.lumina.startup_status()
    assert status["cache"] == "done"
    assert status["cache_progress"] == 1.0
    assert status["cache_detail"] is None


async def test_startup_cache_progress_zero_books(test_setup):
    app, _, _ = test_setup
    queue = app.state.lumina.job_queue
    await queue._deferred_startup_work()
    status = app.state.lumina.startup_status()
    assert status["cache"] == "done"
    assert status["cache_progress"] == 1.0
    assert status["cache_detail"] is None
