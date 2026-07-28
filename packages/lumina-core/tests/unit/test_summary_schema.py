"""Summary JSON schema tests."""
import json
import pytest
from lumina_core.summarize.schema import SegmentSummary, parse_segment_summary

def test_parse_valid_summary(llm_fixtures_dir):
    raw = (llm_fixtures_dir / "summary_segment0.json").read_text(encoding="utf-8")
    summary = parse_segment_summary(raw)
    assert len(summary.sentences) <= 3
    assert 3 <= len(summary.bullets) <= 7
    assert len(summary.label) <= 20

def test_label_max_20_chars():
    with pytest.raises(Exception):
        SegmentSummary.model_validate({
            "sentences": ["a"], "bullets": ["b", "c", "d"],
            "label": "这是一段超过二十个汉字限制的段标签内容啊啊啊啊", "anchor": "段 1",
        })

def test_invalid_bullets_count():
    with pytest.raises(Exception):
        parse_segment_summary(json.dumps({
            "sentences": ["a"], "bullets": ["only", "two"],
            "label": "短标签", "anchor": "段 1",
        }))
