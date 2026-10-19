"""Pasted article text becomes one plain-text book."""

from __future__ import annotations

import pytest

from lumina_core.ingest.paste import PASTE_TITLE_MAX_CHARS, PasteImportError, prepare_pasted_text


def test_prepare_uses_first_line_and_normalizes_newlines():
    pasted = prepare_pasted_text("  文章标题\r\n第一段。\r第二段。\n")
    assert pasted.title == "文章标题"
    assert pasted.text == "文章标题\n第一段。\n第二段。"
    again = prepare_pasted_text(pasted.text + "\n")
    assert again.digest == pasted.digest


def test_prepare_truncates_title_and_keeps_body():
    line = "题" * (PASTE_TITLE_MAX_CHARS + 20)
    pasted = prepare_pasted_text(line + "\n正文还在。")
    assert pasted.title == "题" * PASTE_TITLE_MAX_CHARS
    assert pasted.text.startswith(line)


def test_prepare_rejects_blank():
    with pytest.raises(PasteImportError, match="没有可导入的正文"):
        prepare_pasted_text(" \n\t ")


def test_prepare_rejects_over_limit(monkeypatch):
    monkeypatch.setattr("lumina_core.ingest.paste.PASTE_MAX_BYTES", 4)
    with pytest.raises(PasteImportError, match="15MB"):
        prepare_pasted_text("太长了")
