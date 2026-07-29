"""Unit tests for BestBlogs RSS summary parse, rank, and document heuristic."""

from __future__ import annotations

import pytest

from lumina_core.app_state import (
    BESTBLOGS_AI_EN,
    BESTBLOGS_AI_ZH,
    DEFAULT_NEWS_SOURCES,
    OBSOLETE_NEWS_SOURCE_URLS,
    bestblogs_rss_url,
    default_rss_sources,
)
from lumina_core.news.store import NewsSourceRepo
from lumina_core.news.rank import rank_articles, score_article
from lumina_core.news.rss import parse_feed
from lumina_core.news.summary_parse import parse_rss_summary, score_hint_from_parsed, skim_is_rich
from lumina_core.summarize.document import ensure_citations, heuristic_summary


@pytest.fixture
def conn(tmp_path):
    from lumina_core.db.schema import init_db

    return init_db(tmp_path / "test.db")


SAMPLE_SUMMARY = """
📌 一句话摘要
大模型推理成本下降正在加速落地。

📝 详细摘要
多家云厂商宣布降价，推理吞吐提升明显。

💡 主要观点
成本曲线拐点已至。推理优化成为下一阶段核心竞争力。

💬 文章金句
便宜才是硬道理。

📊 文章信息
AI 初评: 88  来源: ExampleBlog  作者: Alice  字数: 1200
"""


def test_bestblogs_default_sources_zh():
    urls = default_rss_sources("zh-CN")
    assert len(urls) == len(DEFAULT_NEWS_SOURCES) == 3
    url_set = {u for u, _ in urls}
    assert BESTBLOGS_AI_ZH in url_set
    assert BESTBLOGS_AI_EN in url_set
    assert any("bestblogs.dev/zh/" in u for u in url_set)
    assert any("bestblogs.dev/en/" in u for u in url_set)
    assert bestblogs_rss_url("en-US") == BESTBLOGS_AI_EN
    assert bestblogs_rss_url("zh-CN") == BESTBLOGS_AI_ZH


def test_default_rss_sources_language_independent():
    assert default_rss_sources("zh-CN") == default_rss_sources("en-US")


def test_ensure_defaults_inserts_and_updates_titles(conn):
    repo = NewsSourceRepo(conn)
    repo.ensure_defaults([("https://example.com/feed", "Old Title")])
    repo.ensure_defaults([("https://example.com/feed", "New Title")])
    rows = repo.list_sources()
    assert len(rows) == 1
    assert rows[0]["title"] == "New Title"


def test_ensure_defaults_bulk_inserts_preset_sources(conn):
    repo = NewsSourceRepo(conn)
    repo.ensure_defaults(default_rss_sources())
    assert len(repo.list_sources()) == 3


def test_prune_obsolete_presets_keeps_custom(conn):
    repo = NewsSourceRepo(conn)
    obsolete_url = next(iter(OBSOLETE_NEWS_SOURCE_URLS))
    repo.add_source(obsolete_url, "Hacker News")
    custom = repo.add_source("https://example.com/custom.xml", "My Feed")
    repo.ensure_defaults(default_rss_sources())
    urls = {r["url"] for r in repo.list_sources()}
    assert obsolete_url not in urls
    assert custom["url"] in urls
    assert len(urls) == 4  # 3 BestBlogs presets + 1 custom


def test_restore_defaults_keeps_custom_sources(conn):
    repo = NewsSourceRepo(conn)
    repo.ensure_defaults(default_rss_sources())
    custom = repo.add_source("https://example.com/custom.xml", "My Feed")
    preset_id = repo.list_sources()[0]["id"]
    repo.delete_source(preset_id)
    assert len(repo.list_sources()) == 3  # 2 presets + 1 custom

    restored = repo.restore_defaults(default_rss_sources())
    assert restored >= 1
    urls = {r["url"] for r in repo.list_sources()}
    assert custom["url"] in urls
    assert len(urls) == 4


def test_parse_rss_summary_bestblogs_sections():
    parsed = parse_rss_summary(SAMPLE_SUMMARY)
    assert "推理成本" in parsed.one_liner
    assert "降价" in parsed.detail
    assert parsed.viewpoints
    assert score_hint_from_parsed(parsed) == 88.0
    assert parsed.meta.get("author") == "Alice"
    assert skim_is_rich(parsed) is True


def test_skim_is_rich_requires_two_viewpoints_without_detail():
    parsed = parse_rss_summary("只有一句很短的 RSS 描述。")
    assert skim_is_rich(parsed) is False
    parsed.viewpoints = ["观点一。", "观点二。"]
    assert skim_is_rich(parsed) is True


def test_parse_feed_prefers_one_liner():
    feed = f"""<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <title>BestBlogs</title>
      <item>
        <title>Test Article</title>
        <link>https://example.com/a1</link>
        <description><![CDATA[{SAMPLE_SUMMARY}]]></description>
        <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
      </item>
    </channel></rss>
    """.encode()
    articles = parse_feed(feed, source_id="src1")
    assert len(articles) == 1
    assert "推理成本" in articles[0].one_liner
    assert articles[0].excerpt == articles[0].one_liner
    assert articles[0].score_hint == 88.0


def test_rank_prefers_higher_score_hint():
    low = {
        "id": "1",
        "title": "Low",
        "published_at": "2024-01-01T00:00:00Z",
        "synced_at": "2024-01-01T00:00:00Z",
        "score_hint": 40,
    }
    high = {
        "id": "2",
        "title": "High",
        "published_at": "2024-01-01T00:00:00Z",
        "synced_at": "2024-01-01T00:00:00Z",
        "score_hint": 90,
    }
    ranked = rank_articles([low, high])
    assert ranked[0].article["id"] == "2"
    assert score_article(high).score > score_article(low).score


def test_heuristic_summary_has_sections():
    md = heuristic_summary(
        "# Intro\n\n这是一篇关于本地大模型的文章。它讨论了推理成本与部署。\n\n## 方法\n\n使用量化与缓存。",
        filename="demo.md",
    )
    assert "## 总结" in md
    assert "## 结构化要点" in md
    fixed, warns = ensure_citations("## 结构化要点\n- **点**：没有索引\n")
    assert "未定位到页/节" in fixed
    assert warns
