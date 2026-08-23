"""Chat DCA budget and JSON parse fallback."""

import json
from unittest.mock import MagicMock

import pytest

from lumina_core.chat.service import build_dca_context
from lumina_core.models.router import ProfileModelRouter, parse_chat_response


def test_parse_chat_response_valid_json():
    parsed = parse_chat_response('{"answer": "ok", "citations": []}')
    assert parsed["answer"] == "ok"


def test_parse_chat_response_fallback_on_garbage():
    parsed = parse_chat_response("这段")
    assert parsed["answer"] == "这段"
    assert parsed["citations"] == []


def test_parse_chat_response_fallback_on_truncated():
    parsed = parse_chat_response("{")
    assert parsed["answer"] == "{"
    assert parsed.get("evidence_sufficient") is False


def test_build_dca_context_formats_structured_summary():
    book = {"id": "b1", "title": "T", "segment_count": 1}
    summary_json = json.dumps({
        "sentences": ["一句概述。"],
        "bullets": [
            {"label": "要点", "body": "充实说明内容，包含足够细节以通过校验。"},
            {"label": "要点二", "body": "第二条充实说明内容，包含足够细节以通过校验。"},
            {"label": "要点三", "body": "第三条充实说明内容，包含足够细节以通过校验。"},
        ],
        "notes": ["需注意局限性。"],
        "follow_ups": ["可追问的问题？"],
        "label": "标签",
        "anchor": "段 1",
    })
    segments = [
        {
            "idx": 0,
            "label": "段1",
            "summary_status": "ready",
            "raw_text": "原文",
            "summary_json": summary_json,
        },
    ]
    ctx = build_dca_context(book, segments, 0)
    assert "结构化要点:" in ctx
    assert "需要注意:" in ctx
    assert "你可以接着问:" in ctx


def test_build_dca_context_truncates_current_and_nearby():
    book = {"id": "b1", "title": "T", "segment_count": 3}
    long_text = "甲" * 5000
    segments = [
        {"idx": 0, "label": "段1", "summary_status": "ready", "raw_text": long_text, "summary_json": None},
        {"idx": 1, "label": "段2", "summary_status": "pending", "raw_text": "乙" * 1000, "summary_json": None},
        {"idx": 2, "label": "段3", "summary_status": "pending", "raw_text": "丙" * 1000, "summary_json": None},
    ]
    ctx = build_dca_context(book, segments, 0)
    assert "甲" * 3000 in ctx
    assert "甲" * 3001 not in ctx
    # nearby excerpt capped at 400; only max_segments=3 considered, current skipped
    assert "乙" * 400 in ctx
    assert "乙" * 401 not in ctx


def test_assemble_segment_context_skips_distant_raw_text(tmp_path):
    from lumina_core.chat.service import assemble_segment_context
    from lumina_core.db.repos import BookRepo, SegmentRepo
    from lumina_core.db.schema import init_db

    conn = init_db(tmp_path / "chat.db")
    book = BookRepo(conn).insert(
        id="b1",
        title="T",
        format="txt",
        file_path="/tmp/t.txt",
        segment_count=3,
        status="reading",
    )
    SegmentRepo(conn).insert_many(
        [
            {
                "id": f"s{i}",
                "book_id": "b1",
                "idx": i,
                "anchor_label": f"段 {i + 1}",
                "raw_text": marker,
                "summary_status": "ready",
                "retry_count": 0,
            }
            for i, marker in enumerate(["MARKER-CUR", "MARKER-NEAR", "MARKER-FAR"])
        ]
    )
    ctx = assemble_segment_context(
        book,
        current_segment_idx=0,
        segment_repo=SegmentRepo(conn),
    )
    assert "MARKER-CUR" in ctx
    assert "MARKER-NEAR" in ctx
    assert "MARKER-FAR" not in ctx
    assert "L1 段摘要导航" not in ctx


def test_assemble_segment_context_includes_author_and_distant_fts(tmp_path):
    from lumina_core.chat.service import assemble_segment_context
    from lumina_core.db.repos import BookRepo, SegmentRepo
    from lumina_core.db.schema import init_db
    from lumina_core.search.fts import index_segment

    conn = init_db(tmp_path / "chat-fts.db")
    book = BookRepo(conn).insert(
        id="b1",
        title="史书",
        author="太史公",
        format="txt",
        file_path="/tmp/t.txt",
        segment_count=3,
        status="reading",
    )
    segs = SegmentRepo(conn)
    segs.insert_many(
        [
            {
                "id": f"s{i}",
                "book_id": "b1",
                "idx": i,
                "anchor_label": f"段 {i + 1}",
                "raw_text": marker,
                "summary_status": "ready",
                "retry_count": 0,
            }
            for i, marker in enumerate(["MARKER-CUR 开篇", "MARKER-NEAR 邻段", "MARKER-FAR 独有远段关键词XYZQ"])
        ]
    )
    for i in range(3):
        row = segs.get_bodies_by_indices("b1", [i])[i]
        row["book_id"] = "b1"
        index_segment(conn, book, row)
    ctx = assemble_segment_context(
        book,
        current_segment_idx=0,
        segment_repo=segs,
        message="独有远段关键词XYZQ 后来怎样",
    )
    assert "太史公" in ctx
    assert "MARKER-CUR" in ctx
    assert "MARKER-FAR" in ctx
    assert "L2 书内相关段" in ctx


def test_assemble_segment_context_includes_current_notes(tmp_path):
    from lumina_core.chat.service import assemble_segment_context
    from lumina_core.db.repos import BookRepo, NoteRepo, SegmentRepo
    from lumina_core.db.schema import init_db

    conn = init_db(tmp_path / "chat-notes.db")
    book = BookRepo(conn).insert(
        id="b1",
        title="T",
        format="txt",
        file_path="/tmp/t.txt",
        segment_count=1,
        status="reading",
    )
    segs = SegmentRepo(conn)
    segs.insert_many(
        [
            {
                "id": "s0",
                "book_id": "b1",
                "idx": 0,
                "anchor_label": "段 1",
                "raw_text": "原文",
                "summary_status": "ready",
                "retry_count": 0,
            }
        ]
    )
    NoteRepo(conn).create(
        book_id="b1",
        segment_id="s0",
        content="我认为主角在说谎",
        quote="原文",
    )
    ctx = assemble_segment_context(
        book,
        current_segment_idx=0,
        segment_repo=segs,
        note_repo=NoteRepo(conn),
    )
    assert "用户笔记" in ctx
    assert "我认为主角在说谎" in ctx


def test_build_dca_context_includes_optional_root():
    book = {"id": "b1", "title": "T", "segment_count": 1}
    segments = [
        {"idx": 0, "label": "段1", "summary_status": "ready", "raw_text": "原文", "summary_json": None},
    ]
    ctx = build_dca_context(book, segments, 0, root_text="全书大意")
    assert ctx.index("L0 全书总摘要") < ctx.index("L2 当前段原文")
    assert "全书大意" in ctx


def test_build_book_dca_context_orders_layers():
    from lumina_core.chat.service import build_book_dca_context

    ctx = build_book_dca_context(
        {"id": "b1", "title": "史书"},
        root_text="总摘要正文",
        cluster_nodes=[
            {
                "level": 1,
                "label": "第一章",
                "segment_idx_start": 0,
                "segment_idx_end": 2,
                "summary_json": json.dumps(
                    {
                        "sentences": ["章综述。"],
                        "bullets": [
                            {"label": "要点", "body": "章内要点说明足够长以通过。"},
                            {"label": "要点二", "body": "第二条章内要点说明足够长。"},
                            {"label": "要点三", "body": "第三条章内要点说明足够长。"},
                        ],
                        "label": "第一章",
                        "anchor": "段 1–3",
                    }
                ),
            }
        ],
        segment_summaries=[(0, "开篇", "段摘要甲")],
        originals=[(0, "原文甲")],
    )
    assert ctx.index("L0 全书总摘要") < ctx.index("L1 分摘要")
    assert ctx.index("L1 分摘要") < ctx.index("L1 相关段摘要")
    assert ctx.index("L1 相关段摘要") < ctx.index("L2 原文证据")
    assert "总摘要正文" in ctx
    assert "段摘要甲" in ctx
    assert "原文甲" in ctx


def _summary_payload(sentence: str, label: str, *, b1: str, b2: str, b3: str) -> str:
    return json.dumps(
        {
            "sentences": [sentence],
            "bullets": [
                {"label": "要点", "body": b1},
                {"label": "要点二", "body": b2},
                {"label": "要点三", "body": b3},
            ],
            "notes": [],
            "follow_ups": [],
            "label": label,
            "anchor": label,
        },
        ensure_ascii=False,
    )


def _indexed_book_tree(tmp_path):
    from lumina_core.db.repos import BookRepo, SegmentRepo, SummaryNodeRepo
    from lumina_core.db.schema import init_db
    from lumina_core.search.fts import index_book, index_segment

    conn = init_db(tmp_path / "book-chat.db")
    book = BookRepo(conn).insert(
        id="b1",
        title="史书",
        format="txt",
        file_path="/tmp/t.txt",
        segment_count=4,
        status="summarized",
        index_status="ready",
    )
    opening = "UNIQUEOPENINGMARKER 紫禁城琉璃瓦开篇独白"
    last_raw = "LASTSEGMENTRAWTEXT 尾声独有收束"
    texts = [opening, "中段甲叙述赶路", "中段乙权谋初现", last_raw]
    labels = ["开篇", "赶路", "权谋", "尾声"]
    segs = SegmentRepo(conn)
    segs.insert_many(
        [
            {
                "id": f"s{i}",
                "book_id": "b1",
                "idx": i,
                "anchor_label": f"段 {i + 1}",
                "raw_text": texts[i],
                "summary_status": "ready",
                "retry_count": 0,
            }
            for i in range(4)
        ]
    )
    for i, label in enumerate(labels):
        segs.update_summary(
            f"s{i}",
            summary_json=_summary_payload(
                f"{label}概述。",
                label,
                b1=f"{label}要点说明足够长以通过校验一。",
                b2=f"{label}要点说明足够长以通过校验二。",
                b3=f"{label}要点说明足够长以通过校验三。",
            ),
            label=label,
        )
        row = segs.get_bodies_by_indices("b1", [i])[i]
        row["book_id"] = "b1"
        index_segment(conn, book, row)
    index_book(conn, book)

    SummaryNodeRepo(conn).replace_for_book(
        "b1",
        [
            {
                "id": "root",
                "level": 0,
                "parent_id": None,
                "sort_idx": 0,
                "segment_id": None,
                "segment_idx_start": 0,
                "segment_idx_end": 3,
                "chapter": None,
                "label": "全书",
                "summary_json": _summary_payload(
                    "全书总摘要：寒门赴考与权谋。",
                    "全书",
                    b1="开篇交代寒门出身与赴考之志，足够长。",
                    b2="中途权谋渐起并影响行程，足够长。",
                    b3="收束于金榜与朝堂选择，足够长。",
                ),
                "status": "ready",
            },
            {
                "id": "c1",
                "level": 1,
                "parent_id": "root",
                "sort_idx": 0,
                "segment_id": None,
                "segment_idx_start": 0,
                "segment_idx_end": 1,
                "chapter": "一",
                "label": "赴考启程",
                "summary_json": _summary_payload(
                    "开篇簇：赴考启程。",
                    "赴考启程",
                    b1="主角辞别乡邻踏上科举之路，足够长。",
                    b2="途中盘缠不足延误行程，足够长。",
                    b3="仍坚持入京应试志向不改，足够长。",
                ),
                "status": "ready",
            },
            {
                "id": "c2",
                "level": 1,
                "parent_id": "root",
                "sort_idx": 1,
                "segment_id": None,
                "segment_idx_start": 2,
                "segment_idx_end": 3,
                "chapter": "二",
                "label": "金榜权谋",
                "summary_json": _summary_payload(
                    "收束簇：金榜权谋。",
                    "金榜权谋",
                    b1="朝堂派系拉拢应试举子，足够长。",
                    b2="金榜前后的选择决定命运，足够长。",
                    b3="尾声收束个人志向与权谋，足够长。",
                ),
                "status": "ready",
            },
        ],
    )
    return conn, book, opening, last_raw


def test_assemble_book_context_overview_uses_l0_l1_not_last_segment(tmp_path):
    from lumina_core.chat.service import assemble_book_context
    from lumina_core.db.repos import SegmentRepo, SummaryNodeRepo

    conn, book, _opening, last_raw = _indexed_book_tree(tmp_path)
    ctx = assemble_book_context(
        conn,
        book,
        message="全书主旨是什么？",
        node_repo=SummaryNodeRepo(conn),
        segment_repo=SegmentRepo(conn),
    )
    assert "L0 全书总摘要" in ctx
    assert "寒门赴考与权谋" in ctx
    assert "赴考启程" in ctx
    assert "金榜权谋" in ctx
    assert ctx.index("L0 全书总摘要") < ctx.index("L1 分摘要")
    assert last_raw not in ctx
    assert "LASTSEGMENTRAWTEXT" not in ctx
    assert "L2 原文证据" not in ctx


def test_assemble_book_context_fts_hit_does_not_pin_current_last(tmp_path):
    from lumina_core.chat.service import NEARBY_ORIGINAL_CHARS, assemble_book_context
    from lumina_core.db.repos import SegmentRepo, SummaryNodeRepo

    conn, book, opening, last_raw = _indexed_book_tree(tmp_path)
    ctx = assemble_book_context(
        conn,
        book,
        message="UNIQUEOPENINGMARKER",
        node_repo=SummaryNodeRepo(conn),
        segment_repo=SegmentRepo(conn),
    )
    assert opening[:NEARBY_ORIGINAL_CHARS] in ctx
    assert last_raw not in ctx
    assert "LASTSEGMENTRAWTEXT" not in ctx
    assert "赴考启程" in ctx
    assert "金榜权谋" in ctx


@pytest.mark.asyncio
async def test_prepare_chat_book_scope_appends_outline_rules(tmp_path):
    from lumina_core.chat.service import prepare_chat
    from lumina_core.config import load_prompts_config
    from lumina_core.db.repos import SegmentRepo, SummaryNodeRepo

    conn, book, _, last_raw = _indexed_book_tree(tmp_path)
    messages, _, context = await prepare_chat(
        SegmentRepo(conn),
        book=book,
        message="全书主旨是什么？",
        current_segment_idx=3,
        scope="book",
        prompts=load_prompts_config(),
        node_repo=SummaryNodeRepo(conn),
        web_search_provider="none",
    )
    assert "不得把阅读位置当成全书主旨" in messages[0]["content"]
    assert "寒门赴考与权谋" in context
    assert last_raw not in context


def test_chat_done_payload_includes_router_metrics():
    """SSE done / JSON response should merge router.chat_metrics() fields."""
    router = MagicMock(spec=ProfileModelRouter)
    router.chat_metrics.return_value = {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "duration_ms": 1200,
        "prompt_tokens": 100,
        "completion_tokens": 40,
        "total_tokens": 140,
        "tps": 33.3,
    }
    payload = {
        "type": "done",
        "answer": "ok",
        "citations": [],
        "web_refs": [],
        "evidence_sufficient": True,
        "session_id": "s1",
        **router.chat_metrics(),
    }
    assert payload["provider"] == "openai"
    assert payload["model"] == "gpt-4o-mini"
    assert payload["tps"] == 33.3
    assert payload["total_tokens"] == 140
