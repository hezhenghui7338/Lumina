"""Ingest format tests."""

from pathlib import Path

import pytest

from lumina_core.ingest.loader import build_segments, load_document


def test_load_txt_roundtrip(tmp_path):
    p = tmp_path / "sample.txt"
    p.write_text("第一章 测试\n\n段落内容。", encoding="utf-8")
    text, meta = load_document(p, "txt")
    assert "段落内容" in text
    assert meta == {}


def test_build_segments_from_txt():
    text = "第一章 开篇\n\n" + ("内容。" * 500)
    segs = build_segments("book-1", text)
    assert len(segs) >= 1
    assert segs[0]["book_id"] == "book-1"


@pytest.mark.skipif(
    not Path("/System/Library/CoreServices/").exists(),
    reason="PDF fixture generation optional",
)
def test_load_pdf_if_pypdf_available(tmp_path):
    pytest.importorskip("pypdf")
    from pypdf import PdfWriter

    p = tmp_path / "mini.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    # blank page has no text — use a writer with metadata only for smoke
    writer.add_metadata({"/Title": "Mini PDF"})
    with p.open("wb") as f:
        writer.write(f)
    text, meta = load_document(p, "pdf")
    assert meta.get("title") == "Mini PDF"
