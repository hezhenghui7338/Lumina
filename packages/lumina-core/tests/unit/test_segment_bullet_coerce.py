"""Segment summary bullet coercion tests."""

from lumina_core.summarize.schema import BulletPoint
from lumina_core.summarize.segment import _parse_summary


def test_parse_summary_coerces_dict_bullets():
    raw = {
        "sentences": ["一句概述。"],
        "bullets": [
            {"label": "学而不倦", "content": "终身学习不懈怠，强调持续精进的重要性。"},
            "plain string with enough length here",
            {"label": "tag", "text": "via text key with sufficient detail"},
        ],
        "label": "论语节选",
        "anchor": "§段 1",
    }
    summary = _parse_summary(raw, fallback_anchor="§段 1")
    assert summary.bullets[0] == BulletPoint(
        label="学而不倦", body="终身学习不懈怠，强调持续精进的重要性。"
    )
    assert summary.bullets[1].body == "plain string with enough length here"
    assert summary.bullets[2] == BulletPoint(label="tag", body="via text key with sufficient detail")


def test_parse_summary_flattens_nested_bullets_and_truncates_label():
    from lumina_core.models.router import parse_json_response

    data = parse_json_response(
        '{"sentences":["一句。"],'
        '"bullets":[["a：1 with enough body text here","b：2 with enough body text here","c：3 with enough body text here"]],'
        '"label":"这是一段超过二十个汉字限制的段标签内容啊啊",'
        '"anchor":"§段 1"}'
    )
    summary = _parse_summary(data, fallback_anchor="§段 1")
    assert len(summary.bullets) == 3
    assert summary.bullets[0].label == "a"
    assert len(summary.label) == 20


def test_parse_summary_legacy_string_bullets():
    raw = {
        "sentences": ["一句概述。"],
        "bullets": ["寒门出身", "自幼苦读", "赴考之志"],
        "label": "引子",
        "anchor": "§段 1",
    }
    summary = _parse_summary(raw, fallback_anchor="§段 1")
    assert len(summary.bullets) == 3
    assert summary.bullets[0].label == "寒门出身"


def test_parse_summary_includes_notes_and_follow_ups():
    raw = {
        "sentences": ["一句概述。"],
        "bullets": [
            {"label": "要点一", "body": "这是第一条要点的充实说明，包含足够细节。"},
            {"label": "要点二", "body": "这是第二条要点的充实说明，包含足够细节。"},
            {"label": "要点三", "body": "这是第三条要点的充实说明，包含足够细节。"},
        ],
        "notes": ["本段信息不完整。"],
        "follow_ups": ["后续如何发展？", "与上段有何关联？"],
        "label": "测试",
        "anchor": "§段 1",
    }
    summary = _parse_summary(raw, fallback_anchor="§段 1")
    assert summary.notes == ["本段信息不完整。"]
    assert len(summary.follow_ups) == 2
