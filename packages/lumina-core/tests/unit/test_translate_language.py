"""Tests for translate/language helpers."""

from __future__ import annotations

from lumina_core.translate.language import (
    book_needs_translation,
    infer_language,
    language_display_name,
    languages_match,
    normalize_lang,
    unexpected_language_span,
)


def test_normalize_lang_zh_variants():
    assert normalize_lang("zh-CN") == "zh"
    assert normalize_lang("zh-Hans") == "zh"
    assert normalize_lang("cmn") == "zh"


def test_normalize_lang_en_variants():
    assert normalize_lang("en-US") == "en"
    assert normalize_lang("en-GB") == "en"


def test_languages_match():
    assert languages_match("zh-CN", "zh")
    assert languages_match("en-US", "en-GB")
    assert not languages_match("zh", "en")
    assert not languages_match(None, "zh")


def test_infer_language_chinese():
    text = "这是一段中文测试文本。" * 20
    assert infer_language(text) == "zh"


def test_infer_language_english():
    text = "This is an English sample paragraph for language detection. " * 10
    assert infer_language(text) == "en"


def test_book_needs_translation_same_language():
    assert not book_needs_translation(
        book_language="zh",
        book_target_language="zh-CN",
        global_target_language="zh-CN",
    )


def test_book_needs_translation_different_language():
    assert book_needs_translation(
        book_language="en",
        book_target_language="zh-CN",
        global_target_language="zh-CN",
    )


def test_book_needs_translation_infers_from_sample():
    sample = "中文段落内容用于推断语言。" * 15
    assert not book_needs_translation(
        book_language=None,
        book_target_language=None,
        global_target_language="zh-CN",
        text_sample=sample,
    )


def test_language_display_name():
    assert language_display_name("zh-CN") == "简体中文"
    assert language_display_name("zh-TW") == "繁体中文"
    assert language_display_name("en-US") == "English"
    assert language_display_name("ja-JP") == "日本語"
    assert language_display_name(None) == "简体中文"


def test_unexpected_language_span_flags_kana_cyrillic_english():
    assert unexpected_language_span(
        "本段交代主角こんにちは离乡赴考。", target_language="zh-CN"
    ) is not None
    assert unexpected_language_span(
        "本段交代 Иван ушёл 离乡。", target_language="zh-CN"
    ) is not None
    leak = unexpected_language_span(
        "This paragraph explains the protagonist left home.",
        target_language="zh-CN",
    )
    assert leak is not None
    assert leak[2] == "夹杂英语整句"


def test_unexpected_language_span_allows_terms_classical_and_source_names():
    assert (
        unexpected_language_span(
            "本段说明主角使用 ChatGPT 与 API 辅助赴考。",
            target_language="zh-CN",
        )
        is None
    )
    assert (
        unexpected_language_span(
            "子曰：学而时习之，不亦说乎？",
            target_language="zh-CN",
        )
        is None
    )
    assert (
        unexpected_language_span(
            "本段提到专名こんにちは出现在信封上。",
            target_language="zh-CN",
            source_text="信封上写着こんにちは。",
        )
        is None
    )
    assert (
        unexpected_language_span(
            "姐姐玛莉拉同意让她去海边。",
            target_language="zh-CN",
            source_text="Marilla said Anne might go to the shore.",
        )
        is None
    )


def test_unexpected_language_span_flags_cjk_latin_glue_and_fragments():
    glue = unexpected_language_span(
        "自家上进心强的姐姐玛莉拉同意让她去海BuilderInterface",
        target_language="zh-CN",
    )
    assert glue is not None
    assert glue[2] == "汉字与拉丁词粘连"

    fragment = unexpected_language_span(
        "我沉思于城市之外的未知lendary世界",
        target_language="zh-CN",
    )
    assert fragment is not None
    assert fragment[2] == "汉字与拉丁词粘连"

    # User sample glues CJK to Latin; spaced phrase still hits the English-clause gate.
    glued_phrase = unexpected_language_span(
        "随后邀请黛西去舞会转而又阻止她along the line",
        target_language="zh-CN",
    )
    assert glued_phrase is not None
    assert glued_phrase[2] == "汉字与拉丁词粘连"

    phrase = unexpected_language_span(
        "随后邀请黛西去舞会转而又阻止她 along the line",
        target_language="zh-CN",
    )
    assert phrase is not None
    assert phrase[2] == "夹杂英语整句"

    vietnamese = unexpected_language_span(
        "我尝试联系梅耶·沃尔夫海姆但未果， bộ lạc failed 苦寻其信息",
        target_language="zh-CN",
    )
    assert vietnamese is not None
    assert vietnamese[2] in {"夹杂带调拉丁字母", "夹杂英语碎片"}

    assert (
        unexpected_language_span(
            "本段说明专名 Marilla 出现在信封上。",
            target_language="zh-CN",
            source_text="信封上写着 Marilla。",
        )
        is None
    )
