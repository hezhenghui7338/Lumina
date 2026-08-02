"""Summary JSON schema tests."""
import json
import pytest
from lumina_core.summarize.schema import (
    BulletPoint,
    SegmentSummary,
    parse_segment_summary,
    parse_segment_summary_minimal,
    validate_summary_richness,
)


def test_parse_valid_summary(llm_fixtures_dir):
    raw = (llm_fixtures_dir / "summary_segment0.json").read_text(encoding="utf-8")
    summary = parse_segment_summary(raw)
    assert len(summary.sentences) <= 3
    assert 3 <= len(summary.bullets) <= 7
    assert len(summary.label) <= 20
    assert all(isinstance(b, BulletPoint) for b in summary.bullets)
    assert summary.notes
    assert len(summary.follow_ups) == 2


def test_label_max_20_chars():
    with pytest.raises(Exception):
        SegmentSummary.model_validate({
            "sentences": ["a"],
            "bullets": [
                {"label": "a", "body": "body one with enough length"},
                {"label": "b", "body": "body two with enough length"},
                {"label": "c", "body": "body three with enough length"},
            ],
            "label": "这是一段超过二十个汉字限制的段标签内容啊啊啊啊",
            "anchor": "段 1",
        })


def test_parse_summary_with_markdown_fence():
    raw = """```json
{
  "sentences": ["一句概述。"],
  "bullets": [
    {"label": "要点一", "body": "第一条要点的充实说明，包含足够细节内容。"},
    {"label": "要点二", "body": "第二条要点的充实说明，包含足够细节内容。"},
    {"label": "要点三", "body": "第三条要点的充实说明，包含足够细节内容。"}
  ],
  "label": "带围栏 JSON",
  "anchor": "§测试 · 段 1"
}
```"""
    summary = parse_segment_summary(raw)
    assert summary.label == "带围栏 JSON"


def test_invalid_bullets_count():
    with pytest.raises(Exception):
        parse_segment_summary(json.dumps({
            "sentences": ["a"],
            "bullets": [
                {"label": "a", "body": "only one with enough length"},
                {"label": "b", "body": "only two with enough length"},
            ],
            "label": "短标签",
            "anchor": "段 1",
        }))


def test_validate_summary_richness_rejects_short_body():
    summary = SegmentSummary.model_validate({
        "sentences": ["a"],
        "bullets": [
            {"label": "短", "body": "太短"},
            {"label": "b", "body": "body two with enough length here"},
            {"label": "c", "body": "body three with enough length here"},
        ],
        "label": "标签",
        "anchor": "段 1",
    })
    with pytest.raises(ValueError, match="body too short"):
        validate_summary_richness(summary)


def test_validate_summary_richness_ollama_threshold():
    summary = SegmentSummary.model_validate({
        "sentences": ["a"],
        "bullets": [
            {"label": "短", "body": "一二三四五六七八九十十二"},
            {"label": "b", "body": "body two with enough length here"},
            {"label": "c", "body": "body three with enough length here"},
        ],
        "label": "标签",
        "anchor": "段 1",
    })
    validate_summary_richness(summary, min_body_chars=12)
    with pytest.raises(ValueError, match="body too short"):
        validate_summary_richness(summary, min_body_chars=20)


def test_legacy_string_bullets_still_parse():
    summary = parse_segment_summary(json.dumps({
        "sentences": ["一句概述。"],
        "bullets": ["寒门出身", "自幼苦读", "赴考之志"],
        "label": "引子",
        "anchor": "段 1",
    }))
    assert len(summary.bullets) == 3


def test_parse_summary_with_prose_wrapped_json():
    raw = """说明文字在前。
{
  "sentences": ["一句概述。"],
  "bullets": [
    {"label": "要点一", "body": "第一条要点的充实说明，包含足够细节内容。"},
    {"label": "要点二", "body": "第二条要点的充实说明，包含足够细节内容。"},
    {"label": "要点三", "body": "第三条要点的充实说明，包含足够细节内容。"}
  ]
}
后面还有说明。"""
    summary = parse_segment_summary_minimal(raw, fallback_anchor="§段 1")
    assert summary.anchor == "§段 1"
    assert summary.notes == []
    assert summary.follow_ups == []


def test_parse_segment_summary_minimal_fills_label_and_anchor():
    raw = {
        "sentences": ["本段交代主角寒门出身与赴考之志。"],
        "bullets": [
            {"label": "寒门出身", "body": "主角生于贫苦农家。"},
            {"label": "赴考之志", "body": "段末誓要金榜题名。"},
            {"label": "邻里关系", "body": "邻里敬其向学。"},
        ],
    }
    summary = parse_segment_summary_minimal(raw, fallback_anchor="§第一章 · 段 1")
    assert summary.anchor == "§第一章 · 段 1"
    assert summary.label.startswith("本段")
    assert len(summary.label) <= 20
    assert summary.notes == []
    assert summary.follow_ups == []


def test_parse_segment_summary_minimal_preserves_follow_ups():
    raw = {
        "sentences": ["本段交代主角寒门出身与赴考之志。"],
        "bullets": [
            {"label": "寒门出身", "body": "主角生于贫苦农家。"},
            {"label": "赴考之志", "body": "段末誓要金榜题名。"},
            {"label": "邻里关系", "body": "邻里敬其向学。"},
        ],
        "follow_ups": ["主角与邻里期望之间有何张力？", "赴考之志在后文如何遭遇挫折？"],
    }
    summary = parse_segment_summary_minimal(raw, fallback_anchor="§第一章 · 段 1")
    assert summary.follow_ups == [
        "主角与邻里期望之间有何张力？",
        "赴考之志在后文如何遭遇挫折？",
    ]


@pytest.mark.asyncio
async def test_summarize_segment_dumps_raw_on_failure(tmp_path):
    from lumina_core.summarize.segment import summarize_segment

    class BadRouter:
        async def complete(self, prompt, profile="summarize", json_mode=True, **kwargs):
            return "not json"

    dump = tmp_path / "fail.txt"
    with pytest.raises(json.JSONDecodeError):
        await summarize_segment(
            BadRouter(),
            raw_text="hello",
            anchor_label="§段 1",
            max_retries=1,
            failure_dump_path=dump,
        )
    assert dump.read_text(encoding="utf-8") == "not json"
