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
    conn.commit()
    index_book(conn, book)
    note = {
        "id": "n1",
        "book_id": "b1",
        "content": "反向传播算法要点",
        "quote": None,
    }
    conn.execute(
        """
        INSERT INTO notes (id, book_id, content, type, created_at)
        VALUES ('n1', 'b1', '反向传播算法要点', 'manual', 'now')
        """
    )
    conn.commit()
    index_note(conn, book, note)
    hits = search(conn, "反向传播")
    assert any(h["kind"] == "note" for h in hits)


def test_news_brief_empty(conn):
    brief = build_brief(conn)
    assert brief["count"] == 0


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
