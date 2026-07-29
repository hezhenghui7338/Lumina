"""Unit tests for news brief cards."""

from __future__ import annotations

from lumina_core.db.schema import init_db
from lumina_core.news.brief import build_brief
from lumina_core.news.store import NewsArticle, NewsStore
from lumina_core.news.summary_parse import skim_is_rich, parse_rss_summary


def test_skim_is_rich_bestblogs_sample():
    parsed = parse_rss_summary(
        "📌 一句话摘要\n简短。\n\n📝 详细摘要\n"
        + ("这是一段足够长的详细摘要内容。" * 5)
        + "\n\n💡 主要观点\n观点一。观点二。"
    )
    assert skim_is_rich(parsed) is True


def test_skim_is_rich_sparse_fallback():
    parsed = parse_rss_summary("只有一句很短的 RSS 描述。")
    assert skim_is_rich(parsed) is False


def test_build_brief_includes_skim_rich_and_summary_status(tmp_path):
    conn = init_db(tmp_path / "brief.db")
    store = NewsStore(conn)
    store.upsert(
        NewsArticle(
            id="sparse1",
            source_id="src1",
            url="https://example.com/sparse",
            title="Sparse",
            excerpt="Short.",
            rss_summary="Short RSS only.",
            one_liner="Short.",
            summary_status="idle",
        )
    )
    store.upsert(
        NewsArticle(
            id="ready1",
            source_id="src1",
            url="https://example.com/ready",
            title="Ready",
            excerpt="Also short.",
            rss_summary="Also short.",
            one_liner="Also short.",
            summary_markdown="## 总结\nCached.",
            summary_status="ready",
        )
    )

    brief = build_brief(conn, limit=10)
    by_id = {a["id"]: a for a in brief["articles"]}

    assert by_id["sparse1"]["skim_rich"] is False
    assert by_id["sparse1"]["summary_status"] == "idle"
    assert by_id["ready1"]["skim_rich"] is False
    assert by_id["ready1"]["summary_status"] == "ready"
