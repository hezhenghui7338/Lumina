"""Tests for translate/language helpers."""

from __future__ import annotations

from lumina_core.translate.language import (
    book_needs_translation,
    infer_language,
    languages_match,
    normalize_lang,
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
