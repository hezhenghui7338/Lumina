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
            "summarize": load_json_fixture(LLM_FIXTURES / "summary_segment0.json"),
            "chat": load_json_fixture(LLM_FIXTURES / "chat_with_citation.json"),
            "translate": "示例译文。",
        }
    )
    app = create_app(Settings(data_dir=tmp_path, auto_start_summary=True))
    app.state.lumina.router = router
    app.state.lumina.job_queue.router = router
    set_router(router)
    with TestClient(app) as c:
        yield c


def test_create_note_and_search(client):
    book_id = import_sample_book(client)
    segs = client.get(f"/books/{book_id}/segments").json()["segments"]
    assert segs
    segment_id = segs[0]["id"]

    missing = client.post(
        "/notes",
        json={"book_id": book_id, "content": "无段笔记", "type": "manual"},
    )
    assert missing.status_code == 422

    bad_seg = client.post(
        "/notes",
        json={
            "book_id": book_id,
            "content": "错误段",
            "type": "manual",
            "segment_id": "nonexistent-segment",
        },
    )
    assert bad_seg.status_code == 400

    note = client.post(
        "/notes",
        json={
            "book_id": book_id,
            "content": "反向传播要点",
            "type": "manual",
            "segment_id": segment_id,
        },
    )
    assert note.status_code == 200
    body = note.json()
    assert body["content"] == "反向传播要点"
    assert body["segment_id"] == segment_id
    assert body["segment_index"] == segs[0]["idx"]
    assert body["segment_label"]
    assert body["book_title"]

    book_notes = client.get("/notes", params={"book_id": book_id}).json()["notes"]
    assert len(book_notes) >= 1
    assert book_notes[0]["segment_index"] == segs[0]["idx"]

    filtered = client.get(
        "/notes", params={"book_id": book_id, "segment_id": segment_id}
    ).json()["notes"]
    assert all(n["segment_id"] == segment_id for n in filtered)

    all_notes = client.get("/notes").json()["notes"]
    assert any(n["id"] == body["id"] and n.get("book_title") for n in all_notes)

    hits = client.get("/search", params={"q": "反向传播"}).json()["results"]
    note_hits = [h for h in hits if h["kind"] == "note"]
    assert note_hits
    assert note_hits[0].get("segment_index") == segs[0]["idx"]

    deleted = client.delete(f"/notes/{body['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"

    assert client.get("/notes", params={"book_id": book_id}).json()["notes"] == []
    hits_after = client.get("/search", params={"q": "反向传播"}).json()["results"]
    assert not any(h["kind"] == "note" and h.get("note_id") == body["id"] for h in hits_after)

    missing = client.delete("/notes/nonexistent-note-id")
    assert missing.status_code == 404


def test_chat_with_quote(client):
    book_id = import_sample_book(client)

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
    body = resp.json()
    assert body["answer"]
    assert body["provider"] == "ollama"
    assert body["model"]
    assert body["total_tokens"] == 160
    assert body["tps"] == 50.0


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


def test_news_ops_do_not_pause_library_job_queue(client):
    """资讯精读/深聊不得 pause 书库 JobQueue，两边可并行。"""
    conn = client.app.state.lumina.conn  # type: ignore[attr-defined]
    jq = client.app.state.lumina.job_queue  # type: ignore[attr-defined]
    source = NewsSourceRepo(conn).add_source("https://example.com/feed", "Example")
    NewsStore(conn).upsert(
        NewsArticle(
            id="art-parallel",
            source_id=source["id"],
            url="https://example.com/parallel",
            title="Parallel Test",
            excerpt="News must not pause library summarize.",
        )
    )

    book_id = import_sample_book(client)

    assert jq._paused.is_set()

    chat = client.post(
        "/news/articles/art-parallel/chat",
        json={"message": "摘要一下"},
    )
    assert chat.status_code == 200
    assert jq._paused.is_set(), "news chat must not leave library queue paused"

    for _ in range(50):
        segs = client.get(f"/books/{book_id}/segments").json()["segments"]
        if segs and all(s["summary_status"] == "ready" for s in segs):
            break
        time.sleep(0.1)
    else:
        statuses = [
            s["summary_status"]
            for s in client.get(f"/books/{book_id}/segments").json()["segments"]
        ]
        pytest.fail(f"library summarize stalled after news chat: {statuses}")

    assert jq._paused.is_set()


def test_news_sync_bestblogs_and_read(client, monkeypatch, tmp_path):
    """Sync structured BestBlogs-like feed then deep-read with mocked fetch/LLM."""
    from lumina_core.models.router import set_router
    from lumina_core.news.fetch import FetchResult
    from tests.support.mock_router import MockModelRouter

    feed = """<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <title>BestBlogs</title>
      <item>
        <title>AI Cost Drop</title>
        <link>https://publisher.example.com/ai-cost</link>
        <description><![CDATA[
📌 一句话摘要
推理成本显著下降。
📝 详细摘要
云厂商集体降价。
📊 文章信息
AI 初评: 91  字数: 800
        ]]></description>
        <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
      </item>
    </channel></rss>
    """.encode()

    def fake_fetch_feed(url: str, *, timeout: float = 30.0) -> bytes:
        return feed

    def fake_fetch_article(url: str, **kwargs):
        return FetchResult(
            url=url,
            title="AI Cost Drop",
            text=(
                "# AI Cost Drop\n\n"
                "推理成本显著下降。云厂商集体降价，本地部署也更可行。"
                "量化与缓存进一步降低单位 token 成本。"
            )
            * 20,
            strategy="direct",
        )

    monkeypatch.setattr("lumina_core.news.sync.fetch_feed", fake_fetch_feed)
    monkeypatch.setattr("lumina_core.news.read.fetch_article", fake_fetch_article)

    card_md = (
        "## 总结（最多三句话）\n"
        "推理成本显著下降。\n\n"
        "## 结构化要点\n"
        "- **成本**：云厂商降价 — 依据：原文 〔§全文〕\n\n"
        "## 你可以接着问\n"
        "1. 对本地部署有何影响？\n"
    )
    router = MockModelRouter(
        responses={
            "summarize": card_md,
            "chat": {"answer": "文章讲推理成本下降。", "citations": [], "web_refs": [], "evidence_sufficient": True},
        }
    )
    client.app.state.lumina.router = router  # type: ignore[attr-defined]
    client.app.state.lumina.job_queue.router = router  # type: ignore[attr-defined]
    set_router(router)

    conn = client.app.state.lumina.conn  # type: ignore[attr-defined]
    sources = NewsSourceRepo(conn).list_sources()
    assert len(sources) == 3
    assert any("bestblogs.dev/zh/" in s["url"] for s in sources)
    assert any("bestblogs.dev/en/" in s["url"] for s in sources)

    started = time.perf_counter()
    sync = client.post("/news/sync")
    elapsed = time.perf_counter() - started
    assert sync.status_code == 200
    assert any(r["fetched"] >= 1 for r in sync.json()["results"])
    # Mocked feeds: baseline for regression (PRD target 50 articles ≤60s on real network).
    assert elapsed < 30.0

    brief = client.get("/news/brief").json()
    assert brief["count"] >= 1
    art = next(a for a in brief["articles"] if "推理成本" in (a.get("excerpt") or ""))
    assert art.get("one_liner")
    assert art.get("score_hint") == 91.0
    assert art.get("detail")
    assert isinstance(art.get("reasons"), list) and art["reasons"]
    assert isinstance(art.get("viewpoints"), list)
    assert isinstance(art.get("meta"), dict)

    read = client.post(f"/news/articles/{art['id']}/read", json={})
    assert read.status_code == 200
    body = read.json()
    assert "## 总结" in body["summary_markdown"]
    assert body["article"]["summary_status"] == "ready"
    assert body.get("body_text")
    assert "推理成本" in body["body_text"]

    # Cached read path also returns body_text.
    read2 = client.post(f"/news/articles/{art['id']}/read", json={})
    assert read2.status_code == 200
    assert read2.json().get("body_text")

    detail = client.get(f"/news/articles/{art['id']}").json()
    assert detail["fetched_text_path"]
    assert detail["summary_markdown"]

    chat = client.post(
        f"/news/articles/{art['id']}/chat",
        json={"message": "核心观点是什么？"},
    )
    assert chat.status_code == 200
    assert chat.json()["answer"]
    # Chat context should have used cached body (router recorded call).
    chat_calls = [c for c in router.calls if c.get("method") == "chat"]
    assert chat_calls
    prompt = chat_calls[-1]["messages"][-1]["content"]
    assert "正文" in prompt or "推理成本" in prompt
