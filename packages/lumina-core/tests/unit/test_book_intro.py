"""E2E-B14: book-level AI intro triggers, skip, and API shape."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from lumina_core.config import Settings
from lumina_core.db.repos import BookIntroRepo, BookRepo, SegmentRepo
from lumina_core.main import create_app
from lumina_core.models.router import set_router
from lumina_core.summarize.intro import (
    IntroCitation,
    IntroGenerateResult,
    build_intro_query,
    generate_book_intro,
)
from lumina_core.summarize.schema import BulletPoint, SegmentSummary
from tests.support.import_helpers import import_sample_book
from tests.support.mock_router import MockModelRouter, load_json_fixture

LLM_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "llm"


def _sample_summary() -> SegmentSummary:
    return SegmentSummary(
        sentences=["导读一句。"],
        bullets=[
            BulletPoint(label="背景", body="这是足够长的导读要点正文用来通过校验。"),
            BulletPoint(label="作者", body="这是足够长的导读要点正文用来通过校验。"),
            BulletPoint(label="主题", body="这是足够长的导读要点正文用来通过校验。"),
        ],
        notes=[],
        follow_ups=["问什么？", "再问？"],
        label="AI导读",
        anchor="AI导读",
    )


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
    app = create_app(Settings(data_dir=tmp_path, web_search_enabled=True))
    app.state.lumina.router = router
    app.state.lumina.job_queue.router = router
    set_router(router)
    with TestClient(app) as c:
        yield c


def _wait_scheduled(scheduled: list, *, timeout: float = 3.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if scheduled:
            return
        time.sleep(0.05)


def test_build_intro_query_includes_title_author():
    q = build_intro_query(title="红楼梦", author="曹雪芹", segment0_chapter="第一回")
    assert "红楼梦" in q
    assert "曹雪芹" in q


@pytest.mark.asyncio
async def test_generate_book_intro_skips_when_web_disabled():
    router = MockModelRouter(responses={"summarize": "{}"})
    result = await generate_book_intro(
        router,
        title="Test Book",
        web_search_enabled=False,
    )
    assert result.status == "skipped"


@pytest.mark.asyncio
async def test_generate_book_intro_skips_when_no_sources():
    router = MockModelRouter(responses={"summarize": "{}"})
    with patch(
        "lumina_core.summarize.intro.collect_intro_sources",
        new_callable=AsyncMock,
        return_value=("", []),
    ):
        result = await generate_book_intro(
            router,
            title="Obscure Pamphlet XYZ",
            web_search_enabled=True,
        )
    assert result.status == "skipped"


def test_get_intro_idle_for_new_book(client):
    book_id = import_sample_book(client)
    resp = client.get(f"/books/{book_id}/intro")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "idle"
    assert body["summary"] is None
    assert body["citations"] == []


def test_manual_generate_acks_pending(client, monkeypatch):
    book_id = import_sample_book(client)
    monkeypatch.setattr(
        client.app.state.lumina.job_queue,
        "schedule_intro_after_claim",
        lambda *_a, **_k: None,
    )
    resp = client.post(f"/books/{book_id}/intro/generate")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    stored = BookIntroRepo(client.app.state.lumina.conn).get_or_idle(book_id)
    assert stored["status"] == "pending"


def test_start_from_zero_schedules_intro(client):
    book_id = import_sample_book(client)
    jq = client.app.state.lumina.job_queue
    scheduled: list[tuple[str, bool]] = []

    def _capture(bid: str, *, force: bool = False) -> None:
        scheduled.append((bid, force))

    jq.schedule_intro = _capture  # type: ignore[method-assign]

    progress = BookRepo(client.app.state.lumina.conn).summary_progress(book_id)
    assert int(progress["summary_ready_count"] or 0) == 0

    resp = client.post(f"/books/{book_id}/summarize/start")
    assert resp.status_code == 200
    _wait_scheduled(scheduled)
    assert scheduled[0][0] == book_id
    assert scheduled[0][1] is False


def test_start_with_ready_does_not_schedule_intro(client):
    book_id = import_sample_book(client)
    jq = client.app.state.lumina.job_queue
    scheduled: list[tuple[str, bool]] = []
    jq.schedule_intro = lambda bid, *, force=False: scheduled.append((bid, force))  # type: ignore

    segs = SegmentRepo(client.app.state.lumina.conn).list_for_book(
        book_id, include_body=False
    )
    assert segs
    SegmentRepo(client.app.state.lumina.conn).set_status(segs[0]["id"], "ready")
    progress = BookRepo(client.app.state.lumina.conn).summary_progress(book_id)
    assert int(progress["summary_ready_count"] or 0) >= 1

    scheduled.clear()
    resp = client.post(f"/books/{book_id}/summarize/start")
    assert resp.status_code == 200
    time.sleep(0.3)
    assert scheduled == []


def test_regenerate_schedules_intro_force(client):
    book_id = import_sample_book(client)
    jq = client.app.state.lumina.job_queue
    scheduled: list[tuple[str, bool]] = []
    jq.schedule_intro = lambda bid, *, force=False: scheduled.append((bid, force))  # type: ignore

    resp = client.post(f"/books/{book_id}/summarize/regenerate")
    assert resp.status_code == 200
    assert scheduled
    assert scheduled[0] == (book_id, True)


def test_force_false_skips_ready_intro(client):
    book_id = import_sample_book(client)
    BookIntroRepo(client.app.state.lumina.conn).upsert(
        book_id,
        status="ready",
        source_text="wiki text",
        summary_json=_sample_summary().model_dump(),
        citations=[{"title": "Wiki", "url": "https://example.com", "source": "Wikipedia"}],
    )
    jq = client.app.state.lumina.job_queue

    asyncio.run(jq._run_intro(book_id, force=False, already_claimed=False))
    row = BookIntroRepo(client.app.state.lumina.conn).get_or_idle(book_id)
    assert row["status"] == "ready"
    assert row["source_text"] == "wiki text"


@pytest.mark.asyncio
async def test_run_intro_persists_ready(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMINA_DATA_DIR", str(tmp_path))
    router = MockModelRouter(
        responses={"summarize": load_json_fixture(LLM_FIXTURES / "summary_segment0.json")}
    )
    app = create_app(Settings(data_dir=tmp_path, web_search_enabled=True))
    app.state.lumina.router = router
    app.state.lumina.job_queue.router = router
    set_router(router)
    with TestClient(app) as client:
        book_id = import_sample_book(client)
        fake = IntroGenerateResult(
            status="ready",
            source_text="Encyclopedia body",
            summary=_sample_summary(),
            citations=[
                IntroCitation(title="Wiki", url="https://ex.com", source="Wikipedia")
            ],
        )
        with patch(
            "lumina_core.summarize.intro.generate_book_intro",
            new_callable=AsyncMock,
            return_value=fake,
        ):
            jq = client.app.state.lumina.job_queue
            await jq._run_intro(book_id, force=True, already_claimed=False)

        row = BookIntroRepo(client.app.state.lumina.conn).get_or_idle(book_id)
        assert row["status"] == "ready"
        assert row["source_text"] == "Encyclopedia body"
        assert row["summary"] is not None
        assert row["citations"]
