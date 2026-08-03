"""Chat DCA budget and JSON parse fallback."""

import json
from unittest.mock import MagicMock

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
