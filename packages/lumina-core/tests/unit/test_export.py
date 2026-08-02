"""Markdown export tests."""

import json

from starlette.responses import PlainTextResponse

from lumina_core.export.markdown import (
    content_disposition_attachment,
    export_book_markdown,
    render_segment_summary_for_export,
)


def test_content_disposition_attachment_latin1_safe():
    header = content_disposition_attachment("三体-summary.md")
    header.encode("latin-1")
    assert 'filename="summary.md"' in header
    assert "filename*=UTF-8''" in header
    assert "%E4%B8%89%E4%BD%93" in header


def test_content_disposition_plaintext_response_with_chinese_title():
    filename = "三体-summary.md"
    response = PlainTextResponse(
        "test",
        headers={"Content-Disposition": content_disposition_attachment(filename)},
    )
    assert response.headers["Content-Disposition"].encode("latin-1")


def test_export_includes_translation_by_default():
    book = {"title": "Test Book", "author": "Author", "format": "txt", "segment_count": 1}
    segments = [
        {
            "idx": 0,
            "anchor_label": "〔段 1〕",
            "summary_json": json.dumps(
                {
                    "sentences": ["一句摘要。"],
                    "bullets": [
                        {"label": "要点", "body": "充实说明内容，包含足够细节以通过校验。"},
                        {"label": "要点二", "body": "第二条充实说明内容，包含足够细节以通过校验。"},
                        {"label": "要点三", "body": "第三条充实说明内容，包含足够细节以通过校验。"},
                    ],
                    "notes": ["需注意局限性。"],
                    "follow_ups": ["可追问的问题？"],
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
    assert "需要注意" in md
    assert "你可以接着问" in md
    assert "Translated paragraph." in md
    assert "译文" in md


def test_export_lenient_partial_summary():
    """Partial summary (UI-visible) exports readable Markdown without strict schema."""
    partial = {
        "sentences": ["只有一句总结。"],
        "bullets": [{"label": "要点", "body": "单条要点说明。"}],
        "notes": [],
        "follow_ups": [],
    }
    rendered = render_segment_summary_for_export(partial)
    assert "只有一句总结。" in rendered
    assert any("单条要点说明" in line for line in rendered)

    book = {"title": "Partial", "author": None, "format": "txt", "segment_count": 1}
    segments = [
        {
            "idx": 0,
            "anchor_label": "〔段 1〕",
            "summary_json": json.dumps(partial),
        }
    ]
    md = export_book_markdown(book, segments)
    assert "只有一句总结。" in md
    assert "单条要点说明" in md
    assert "_摘要未生成_" not in md


def test_export_with_notes_optional():
    book = {"title": "Notes Book", "author": "A", "format": "txt", "segment_count": 1}
    segments = [
        {
            "idx": 0,
            "anchor_label": "〔段 1〕",
            "summary_json": json.dumps(
                {
                    "sentences": ["摘要句。"],
                    "bullets": [
                        {"label": "一", "body": "第一条要点内容足够长。"},
                        {"label": "二", "body": "第二条要点内容足够长。"},
                        {"label": "三", "body": "第三条要点内容足够长。"},
                    ],
                    "notes": [],
                    "follow_ups": [],
                    "label": "标签",
                    "anchor": "段 1",
                }
            ),
        }
    ]
    notes = [{"content": "我的第一条笔记"}, {"content": "段内批注"}]

    md_without = export_book_markdown(book, segments, include_notes=False)
    assert "## 我的笔记" not in md_without

    md_with = export_book_markdown(book, segments, include_notes=True, notes=notes)
    assert "## 我的笔记" in md_with
    assert "我的第一条笔记" in md_with
    assert "段内批注" in md_with
