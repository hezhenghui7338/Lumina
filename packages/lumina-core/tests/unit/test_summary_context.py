"""Sequential summary context selection and prompt injection."""

from __future__ import annotations

import json
import uuid

import pytest

from lumina_core.db.repos import BookRepo, SegmentRepo
from lumina_core.db.schema import init_db
from lumina_core.summarize.segment import build_summary_context, summarize_segment
from tests.support.mock_router import MockModelRouter


def _summary(sentence: str, body: str) -> str:
    return json.dumps(
        {
            "sentences": [sentence],
            "bullets": [{"label": "人物", "body": body}],
            "notes": [],
            "follow_ups": [],
            "label": "人物关系",
            "anchor": "段",
        },
        ensure_ascii=False,
    )


def test_build_summary_context_uses_current_and_previous_chapter() -> None:
    rows = [
        {"idx": 4, "chapter": "第二章", "summary_json": _summary("本章前文", "我独自离开")},
        {"idx": 3, "chapter": "第一章", "summary_json": _summary("上一章结尾", "林明留在家中")},
        {"idx": 2, "chapter": "第一章", "summary_json": _summary("上一章前文", "叙述者与林明交谈")},
        {"idx": 1, "chapter": "序章", "summary_json": _summary("更早内容", "不应进入背景")},
    ]

    context = build_summary_context(rows, current_chapter="第二章")

    assert context is not None
    assert "[上一章·段 3]" in context
    assert "[上一章·段 4]" in context
    assert "[本章前文·段 5]" in context
    assert context.index("段 3") < context.index("段 4") < context.index("段 5")
    assert "更早内容" not in context


def test_build_summary_context_without_chapter_falls_back_and_truncates() -> None:
    rows = [
        {"idx": idx, "chapter": None, "summary_json": _summary(f"摘要{idx}", "甲" * 80)}
        for idx in range(8, -1, -1)
    ]

    context = build_summary_context(rows, current_chapter=None, max_chars=120)

    assert context is not None
    assert len(context) <= 120
    assert "[前文·段 9]" in context


def test_repo_previous_summary_query_is_slim_and_ordered(tmp_path) -> None:
    conn = init_db(tmp_path / "context.db")
    BookRepo(conn).insert(
        id="book",
        title="Test",
        format="txt",
        file_path="/tmp/test.txt",
        segment_count=3,
        status="processing",
    )
    repo = SegmentRepo(conn)
    repo.insert_many(
        [
            {
                "id": str(uuid.uuid4()),
                "book_id": "book",
                "idx": idx,
                "chapter": "第一章",
                "anchor_label": f"段 {idx + 1}",
                "raw_text": "不应被查询",
                "summary_status": "pending",
                "retry_count": 0,
            }
            for idx in range(3)
        ]
    )
    for idx in (0, 1):
        seg = repo.get_by_index("book", idx)
        assert seg is not None
        repo.update_summary(
            seg["id"],
            summary_json=_summary(f"摘要{idx}", "人物关系"),
            label=f"摘要{idx}",
            status="ready",
        )

    rows = repo.list_ready_summaries_before("book", 2)

    assert [row["idx"] for row in rows] == [1, 0]
    assert all(set(row) == {"idx", "chapter", "summary_json"} for row in rows)


@pytest.mark.asyncio
async def test_prompt_injects_context_as_disambiguation_only() -> None:
    response = {
        "sentences": ["我想起了小时候的往事。"],
        "bullets": [
            {"label": "回忆", "body": "林明走后，我独自回想童年经历。"},
            {"label": "身份", "body": "当前段没有明确说明我的姓名。"},
            {"label": "关系", "body": "林明只是背景中出现的人物。"},
        ],
        "follow_ups": [],
    }
    router = MockModelRouter(responses={"summarize": response})

    await summarize_segment(
        router,
        raw_text="林明走后，我想起了小时候。",
        anchor_label="第二章 · 段 1",
        background_context="[上一章·段 2] 林明留在家中。",
        max_retries=1,
    )

    prompt = router.calls[0]["prompt"]
    assert "仅用于消解人物、代词、时间线和因果关系" in prompt
    assert "不能把背景中的事件当作当前段内容" in prompt
    assert "不得仅因段首出现某个人名" in prompt
    assert "阅读助手" in prompt
    assert "禁止写成「叙述者」" in prompt
    assert "[上一章·段 2] 林明留在家中。" in prompt
    assert "林明走后，我想起了小时候。" in prompt
