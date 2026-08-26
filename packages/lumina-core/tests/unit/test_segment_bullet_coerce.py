"""Segment summary bullet coercion tests."""

from lumina_core.summarize.schema import BulletPoint, parse_segment_summary_minimal


def test_parse_summary_coerces_dict_bullets():
    raw = {
        "sentences": ["一句概述。"],
        "bullets": [
            {"label": "学而不倦", "content": "终身学习不懈怠，强调持续精进的重要性。"},
            "plain string with enough length here",
            {"label": "tag", "text": "via text key with sufficient detail"},
        ],
    }
    summary = parse_segment_summary_minimal(raw, fallback_anchor="§段 1")
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
        '"label":"这是一段超过二十个汉字限制的段标签内容啊啊"}'
    )
    summary = parse_segment_summary_minimal(data, fallback_anchor="§段 1")
    assert len(summary.bullets) == 3
    assert summary.bullets[0].label == "a"
    assert len(summary.label) <= 20


def test_parse_summary_legacy_string_bullets():
    raw = {
        "sentences": ["一句概述。"],
        "bullets": ["寒门出身", "自幼苦读", "赴考之志"],
    }
    summary = parse_segment_summary_minimal(raw, fallback_anchor="§段 1")
    assert len(summary.bullets) == 3
    assert summary.bullets[0].label == "寒门出身"


def test_segment_list_preview_uses_sentence_not_inferred_label():
    from lumina_core.summarize.preview import segment_list_preview

    payload = {
        "sentences": ["邻里虽敬其向学，却无力资助书卷。"],
        "bullets": [{"label": "邻里", "body": "乡邻敬其向学但无力资助。"}],
        "label": "邻里虽敬",
    }
    preview = segment_list_preview(payload)
    assert preview == "邻里虽敬其向学，却无力资助书卷。"
    assert preview != "邻里虽敬"


def test_segment_list_bullet_labels_extracts_titles_not_bodies():
    from lumina_core.summarize.preview import segment_list_bullet_labels, segment_list_fields

    payload = {
        "sentences": ["邻里虽敬其向学，却无力资助书卷。"],
        "bullets": [
            {"label": "寒门出身", "body": "主角生于贫苦农家。"},
            {"label": "赴考之志", "body": "段末誓要金榜题名。"},
            "邻里期望：乡邻将其视为希望。",
        ],
        "label": "寒门",
    }
    assert segment_list_bullet_labels(payload) == ["寒门出身", "赴考之志", "邻里期望"]
    preview, labels = segment_list_fields(payload)
    assert preview == "邻里虽敬其向学，却无力资助书卷。"
    assert labels == ["寒门出身", "赴考之志", "邻里期望"]
    assert segment_list_bullet_labels(None) == []


def test_segment_list_preview_falls_back_to_bullets_and_clips():
    from lumina_core.summarize.preview import LIST_PREVIEW_MAX_CHARS, segment_list_preview

    payload = {
        "sentences": [],
        "bullets": [
            {"label": "寒门出身", "body": "主角生于贫苦农家。"},
            {"label": "赴考之志", "body": "段末誓要金榜题名。"},
        ],
        "label": "寒门",
    }
    preview = segment_list_preview(payload)
    assert preview and "寒门出身" in preview
    assert "主角生于贫苦农家" in preview

    long_sentence = "甲" * 200
    clipped = segment_list_preview({"sentences": [long_sentence], "bullets": []})
    assert clipped is not None
    assert len(clipped) == LIST_PREVIEW_MAX_CHARS
    assert clipped.endswith("…")


def test_parse_summary_preserves_optional_notes_when_present():
    raw = {
        "sentences": ["一句概述。"],
        "bullets": [
            {"label": "要点一", "body": "这是第一条要点的充实说明，包含足够细节。"},
            {"label": "要点二", "body": "这是第二条要点的充实说明，包含足够细节。"},
            {"label": "要点三", "body": "这是第三条要点的充实说明，包含足够细节。"},
        ],
        "notes": ["本段信息不完整。"],
        "follow_ups": ["后续如何发展？", "与上段有何关联？"],
    }
    summary = parse_segment_summary_minimal(raw, fallback_anchor="§段 1")
    assert summary.notes == ["本段信息不完整。"]
    assert len(summary.follow_ups) == 2
