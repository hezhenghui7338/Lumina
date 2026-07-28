"""Markdown export tests."""

import json

from lumina_core.export.markdown import export_book_markdown


def test_export_includes_translation_by_default():
    book = {"title": "Test Book", "author": "Author", "format": "txt", "segment_count": 1}
    segments = [
        {
            "idx": 0,
            "anchor_label": "〔段 1〕",
            "summary_json": json.dumps(
                {
                    "sentences": ["一句摘要。"],
                    "bullets": ["a", "b", "c"],
                    "label": "标签",
                    "anchor": "段 1",
                }
            ),
            "translation": "Translated paragraph.",
        }
    ]
    md = export_book_markdown(book, segments)
    assert "摘要版" in md
    assert "一句摘要" in md
    assert "Translated paragraph." in md
    assert "译文" in md
