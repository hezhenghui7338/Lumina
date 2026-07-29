"""FTS and news tests."""

import sqlite3

import pytest

from lumina_core.db.schema import init_db
from lumina_core.news.brief import build_brief
from lumina_core.news.rss import excerpt_from_summary
from lumina_core.news.store import NewsArticle, NewsSourceRepo, NewsStore
from lumina_core.search.fts import index_book, index_note, search


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "test.db")


def test_excerpt_truncation():
    long_text = "A" * 300
    assert len(excerpt_from_summary(long_text)) <= 220


def test_fts_search_book_and_note(conn):
    book = {
        "id": "b1",
        "title": "深度学习入门",
        "author": "张三",
    }
    conn.execute(
        """
        INSERT INTO books (id, title, author, format, file_path, created_at, updated_at)
        VALUES ('b1', '深度学习入门', '张三', 'txt', '/x', 'now', 'now')
        """
    )
    conn.execute(
        """
        INSERT INTO segments (id, book_id, idx, raw_text, summary_status)
        VALUES ('s1', 'b1', 0, '正文', 'ready')
        """
    )
    conn.commit()
    index_book(conn, book)
    note = {
        "id": "n1",
        "book_id": "b1",
        "segment_id": "s1",
        "content": "反向传播算法要点",
        "quote": None,
    }
    conn.execute(
        """
        INSERT INTO notes (id, book_id, segment_id, content, type, created_at)
        VALUES ('n1', 'b1', 's1', '反向传播算法要点', 'manual', 'now')
        """
    )
    conn.commit()
    index_note(conn, book, note)
    hits = search(conn, "反向传播")
    assert any(h["kind"] == "note" for h in hits)
    note_hit = next(h for h in hits if h["kind"] == "note")
    assert note_hit.get("segment_index") == 0


def test_news_brief_empty(conn):
    brief = build_brief(conn)
    assert brief["count"] == 0


def test_news_brief_structured_fields(conn):
    source = NewsSourceRepo(conn).add_source("https://example.com/feed", "Example")
    store = NewsStore(conn)
    rss = (
        "📌 一句话摘要 这是一句摘要。"
        "📝 详细摘要 这是更长的详细摘要内容，说明背景与影响。"
        "💡 主要观点 观点甲。补充说明观点甲的细节内容需要足够长才算笔记。"
        "观点乙。"
        "💬 文章金句 金句一。"
        "📊 文章信息 AI初评: 88 来源: ExampleBlog 阅读时间: 5分钟"
    )
    store.upsert(
        NewsArticle(
            id="art1",
            source_id=source["id"],
            url="https://example.com/1",
            title="测试文章",
            excerpt="fallback",
            rss_summary=rss,
            one_liner="这是一句摘要。",
            score_hint=88.0,
            published_at="2026-07-28T10:00:00+00:00",
        )
    )
    brief = build_brief(conn, limit=10)
    assert brief["count"] == 1
    card = brief["articles"][0]
    assert card["id"] == "art1"
    assert card["one_liner"]
    assert card["detail"]
    assert isinstance(card["viewpoints"], list) and card["viewpoints"]
    assert isinstance(card["quotes"], list)
    assert isinstance(card["meta"], dict)
    assert "ai_score" in card["meta"] or card["score_hint"] == 88.0
    assert isinstance(card["reasons"], list) and card["reasons"]
    assert card["source_id"] == source["id"]
    assert card["source_title"] == "Example"
    assert card["source"] == "Example"


def test_news_brief_default_limit(conn):
    source = NewsSourceRepo(conn).add_source("https://example.com/feed", "Example")
    store = NewsStore(conn)
    for i in range(40):
        store.upsert(
            NewsArticle(
                id=f"art{i}",
                source_id=source["id"],
                url=f"https://example.com/{i}",
                title=f"Article {i}",
                excerpt="x",
                score_hint=float(i),
                published_at=f"2026-07-28T{10 + i % 10:02d}:00:00+00:00",
            )
        )
    brief = build_brief(conn)
    assert brief["count"] == 25


def test_news_brief_limit(conn):
    source = NewsSourceRepo(conn).add_source("https://example.com/feed", "Example")
    store = NewsStore(conn)
    for i in range(15):
        store.upsert(
            NewsArticle(
                id=f"art{i}",
                source_id=source["id"],
                url=f"https://example.com/{i}",
                title=f"Article {i}",
                excerpt="x",
                score_hint=float(i),
                published_at=f"2026-07-28T{10 + i % 10:02d}:00:00+00:00",
            )
        )
    brief = build_brief(conn, limit=5)
    assert brief["count"] == 5


def test_news_store_upsert(conn):
    source = NewsSourceRepo(conn).add_source("https://example.com/feed", "Example")
    store = NewsStore(conn)
    art = NewsArticle(
        id="abc",
        source_id=source["id"],
        url="https://example.com/1",
        title="Hello",
        excerpt="World",
    )
    assert store.upsert(art) is True
    assert store.upsert(art) is False
