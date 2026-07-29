"""News deep-read resilience: cache path, stale running recovery, failure states."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from lumina_core.config import Settings
from lumina_core.main import create_app
from lumina_core.models.router import set_router
from lumina_core.news.fetch import FetchResult
from lumina_core.news.store import NewsArticle, NewsSourceRepo, NewsStore
from tests.support.mock_router import MockModelRouter


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMINA_DATA_DIR", str(tmp_path))
    router = MockModelRouter(
        responses={
            "summarize": "## 总结\nCached summary.\n",
            "chat": {"answer": "ok", "citations": [], "web_refs": [], "evidence_sufficient": True},
        }
    )
    app = create_app(Settings(data_dir=tmp_path))
    app.state.lumina.router = router
    app.state.lumina.job_queue.router = router
    set_router(router)
    with TestClient(app) as c:
        yield c


def _seed_article(conn, article_id: str = "art-res", *, summary_status: str = "idle") -> None:
    source = NewsSourceRepo(conn).add_source("https://example.com/feed", "Example")
    NewsStore(conn).upsert(
        NewsArticle(
            id=article_id,
            source_id=source["id"],
            url=f"https://example.com/{article_id}",
            title="Resilience Test",
            excerpt="Excerpt.",
            rss_summary="📌 一句话摘要\n降级摘要。",
            one_liner="降级摘要。",
        )
    )
    if summary_status != "idle":
        NewsStore(conn).update_fields(article_id, summary_status=summary_status)


def test_read_returns_immediately_when_cached(client, monkeypatch, tmp_path):
    conn = client.app.state.lumina.conn  # type: ignore[attr-defined]
    article_id = "art-cached"
    _seed_article(conn, article_id)

    cache_dir = tmp_path / "news_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{article_id}.md"
    cache_path.write_text(
        "# Resilience Test\n\n来源: https://example.com/art-cached\n\n"
        + ("正文内容。" * 80),
        encoding="utf-8",
    )
    NewsStore(conn).update_fields(
        article_id,
        summary_markdown="## 总结\nAlready ready.",
        summary_status="ready",
        fetched_text_path=str(cache_path),
    )

    def fail_fetch(*args, **kwargs):
        raise AssertionError("fetch must not run for cached ready article")

    monkeypatch.setattr("lumina_core.news.read.fetch_article", fail_fetch)

    started = time.monotonic()
    resp = client.post(f"/news/articles/{article_id}/read", json={})
    elapsed = time.monotonic() - started

    assert resp.status_code == 200
    body = resp.json()
    assert body["summary_markdown"].startswith("## 总结")
    assert body.get("body_text")
    assert elapsed < 0.5


def test_stale_running_status_is_reset(client, monkeypatch, tmp_path):
    conn = client.app.state.lumina.conn  # type: ignore[attr-defined]
    article_id = "art-stale"
    _seed_article(conn, article_id, summary_status="running")

    def fake_fetch(url: str, **kwargs):
        return FetchResult(
            url=url,
            title="Resilience Test",
            text=("正文。" * 120),
            strategy="direct",
        )

    monkeypatch.setattr("lumina_core.news.read.fetch_article", fake_fetch)

    resp = client.post(f"/news/articles/{article_id}/read", json={})
    assert resp.status_code == 200
    detail = client.get(f"/news/articles/{article_id}").json()
    assert detail["summary_status"] == "ready"
    assert detail["summary_markdown"]


def test_read_failure_sets_summary_status_failed(client, monkeypatch):
    conn = client.app.state.lumina.conn  # type: ignore[attr-defined]
    article_id = "art-fail"
    source = NewsSourceRepo(conn).add_source("https://example.com/feed", "Example")
    NewsStore(conn).upsert(
        NewsArticle(
            id=article_id,
            source_id=source["id"],
            url=f"https://example.com/{article_id}",
            title="Resilience Test",
            excerpt="",
            rss_summary="",
            one_liner="",
        )
    )

    def bad_fetch(url: str, **kwargs):
        return FetchResult(url=url, title="", text="", strategy="direct", error="fetch blocked")

    monkeypatch.setattr("lumina_core.news.read.fetch_article", bad_fetch)

    resp = client.post(f"/news/articles/{article_id}/read", json={})
    assert resp.status_code == 502
    detail = client.get(f"/news/articles/{article_id}").json()
    assert detail["summary_status"] == "failed"
