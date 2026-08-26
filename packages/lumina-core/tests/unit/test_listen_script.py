"""Listen-script contract: summary / detailed / original, never follow_ups."""

from __future__ import annotations

from lumina_core.tts.script import (
    SECTION_BULLETS,
    SECTION_NOTES,
    build_listen_script,
    detect_language,
)

SAMPLE_SUMMARY = {
    "sentences": [
        "本段交代主角出身寒门。",
        "邻里敬其向学却无力资助。",
    ],
    "bullets": [
        {"label": "寒门出身", "body": "主角生于贫苦农家，父亲早逝。"},
        {"label": "赴考之志", "body": "段末以金榜题名收束。"},
        {"label": "邻里期望", "body": "乡邻视为村庄的希望。"},
    ],
    "notes": ["后文将出现权谋冲突。"],
    "follow_ups": ["主角与邻里期望之间有何张力？"],
    "label": "引子",
    "anchor": "§第一章 · 段 1",
}


def _texts(script) -> list[str]:
    return [u.text for u in script.utterances]


def test_detect_language_cjk_vs_latin():
    assert detect_language("本段交代主角出身寒门。") == "zh"
    assert detect_language("The hero leaves home at dawn.") == "en"


def test_summary_mode_is_sentences_only():
    script = build_listen_script(mode="summary", summary_json=SAMPLE_SUMMARY)
    assert script.ready
    assert script.mode == "summary"
    assert script.language == "zh"
    texts = _texts(script)
    assert texts == SAMPLE_SUMMARY["sentences"]
    joined = "\n".join(texts)
    assert "你可以接着问" not in joined
    assert SAMPLE_SUMMARY["follow_ups"][0] not in joined
    assert SECTION_BULLETS not in joined
    assert "寒门出身" not in joined


def test_detailed_mode_includes_bullets_not_notes_or_follow_ups():
    script = build_listen_script(mode="detailed", summary_json=SAMPLE_SUMMARY)
    assert script.ready
    texts = _texts(script)
    assert texts[0] == SAMPLE_SUMMARY["sentences"][0]
    assert texts[1] == SAMPLE_SUMMARY["sentences"][1]
    assert SECTION_BULLETS in texts
    assert "1. 寒门出身。主角生于贫苦农家，父亲早逝。" in texts
    assert "2. 赴考之志。段末以金榜题名收束。" in texts
    joined = "\n".join(texts)
    assert SECTION_NOTES not in texts
    assert "后文将出现权谋冲突。" not in joined
    assert "你可以接着问" not in joined
    assert "主角与邻里期望之间有何张力？" not in joined


def test_detailed_skips_empty_optional_sections():
    script = build_listen_script(
        mode="detailed",
        summary_json={
            "sentences": ["只有总结。"],
            "bullets": [],
            "notes": [],
            "follow_ups": ["不该读"],
        },
    )
    assert _texts(script) == ["只有总结。"]


def test_original_mode_splits_sentences():
    raw = "第一句。第二句！第三句？Next sentence. Last!"
    script = build_listen_script(mode="original", raw_text=raw)
    assert script.ready
    texts = _texts(script)
    assert texts[0] == "第一句。"
    assert "第二句！" in texts
    assert any("Next sentence." in t or t == "Next sentence." for t in texts)


def test_original_empty_is_not_ready():
    script = build_listen_script(mode="original", raw_text="   ")
    assert not script.ready
    assert script.skip_reason == "empty_text"
    assert script.utterances == []


def test_summary_missing_json_is_not_ready():
    script = build_listen_script(mode="summary", summary_json=None)
    assert not script.ready
    assert script.skip_reason == "summary_not_ready"


def test_json_string_payload_is_accepted():
    import json

    script = build_listen_script(mode="summary", summary_json=json.dumps(SAMPLE_SUMMARY))
    assert script.ready
    assert _texts(script) == SAMPLE_SUMMARY["sentences"]


def test_to_dict_shape():
    script = build_listen_script(mode="summary", summary_json=SAMPLE_SUMMARY)
    payload = script.to_dict()
    assert payload["mode"] == "summary"
    assert payload["ready"] is True
    assert payload["skip_reason"] is None
    assert payload["utterances"][0] == {"text": SAMPLE_SUMMARY["sentences"][0]}


def test_unsupported_mode_raises():
    try:
        build_listen_script(mode="translation", raw_text="x")
    except ValueError as exc:
        assert "unsupported" in str(exc)
    else:
        raise AssertionError("expected ValueError")
