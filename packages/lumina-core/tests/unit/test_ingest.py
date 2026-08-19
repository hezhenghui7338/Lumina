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
    assert segs[0]["char_count"] == len(segs[0]["raw_text"])
    assert sum(s["char_count"] for s in segs) == len(text.strip())


@pytest.mark.skipif(
    not Path("/System/Library/CoreServices/").exists(),
    reason="PDF fixture generation optional",
)
def test_load_pdf_if_pypdf_available(tmp_path, monkeypatch):
    pytest.importorskip("pypdf")
    from pypdf import PdfWriter

    from lumina_core import config
    from lumina_core.ingest.ocr import OcrDocumentResult, OcrPageResult

    p = tmp_path / "mini.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_metadata({"/Title": "Mini PDF"})
    with p.open("wb") as f:
        writer.write(f)

    # Blank page has no text layer — mock OCR so test does not need RapidOCR deps
    monkeypatch.setattr(config, "OCR_ENABLED", True)

    def _fake(_path, **_kwargs):
        return OcrDocumentResult(
            text="## [p.1]\nocr-text",
            pages=[OcrPageResult(1, "ocr-text", 0.9, False)],
            avg_confidence=0.9,
        )

    monkeypatch.setattr("lumina_core.ingest.pdf.ocr_pdf", _fake)
    text, meta = load_document(p, "pdf")
    assert meta.get("title") == "Mini PDF"
    assert "ocr-text" in text
    assert meta.get("ocr_used") is True
    assert meta.get("ocr_pages") == 1


def test_load_pdf_triggers_ocr_when_low_coverage(tmp_path, monkeypatch):
    pytest.importorskip("pypdf")
    from pypdf import PdfWriter

    from lumina_core import config
    from lumina_core.ingest.ocr import OcrDocumentResult, OcrPageResult

    p = tmp_path / "sparse.pdf"
    writer = PdfWriter()
    for _ in range(10):
        writer.add_blank_page(width=200, height=200)
    with p.open("wb") as f:
        writer.write(f)

    monkeypatch.setattr(config, "OCR_ENABLED", True)
    monkeypatch.setattr(config, "OCR_PDF_TEXT_RATIO", 0.15)

    calls: list[dict] = []

    def _fake(_path, **kwargs):
        calls.append(kwargs)
        return OcrDocumentResult(
            text="## [p.1]\nocr-text",
            pages=[OcrPageResult(1, "ocr-text", 0.9, False)],
            avg_confidence=0.9,
        )

    monkeypatch.setattr("lumina_core.ingest.pdf.ocr_pdf", _fake)
    text, meta = load_document(p, "pdf")
    assert calls, "expected OCR for zero-text PDF"
    assert "ocr-text" in text
    assert meta.get("ocr_used") is True


def test_load_pdf_partial_ocr_for_mixed_pages(tmp_path, monkeypatch):
    pytest.importorskip("pypdf")
    fitz = pytest.importorskip("fitz")

    from lumina_core import config
    from lumina_core.ingest.ocr import OcrDocumentResult, OcrPageResult

    p = tmp_path / "mixed.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "text layer page")
    for _ in range(9):
        doc.new_page()
    doc.save(str(p))
    doc.close()

    monkeypatch.setattr(config, "OCR_ENABLED", True)
    monkeypatch.setattr(config, "OCR_PDF_TEXT_RATIO", 0.15)

    def _fake(_path, **kwargs):
        page_nums = kwargs.get("page_nums")
        assert page_nums == list(range(2, 11))
        return OcrDocumentResult(
            text="## [p.2]\nscan-page",
            pages=[OcrPageResult(2, "scan-page", 0.9, False)],
            avg_confidence=0.9,
        )

    monkeypatch.setattr("lumina_core.ingest.pdf.ocr_pdf", _fake)
    text, meta = load_document(p, "pdf")
    assert "text layer page" in text
    assert "scan-page" in text
    assert meta.get("ocr_partial") is True


def _write_epub_with_id_href_mismatch(path: Path) -> None:
    """Typical EPUB: spine idref != file href (e.g. c0_gu_wang_yan vs c0_gu_wang_yan.xhtml)."""
    ebooklib = pytest.importorskip("ebooklib")
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("lumina-epub-test")
    book.set_title("姑妄言")
    book.add_author("曹去晶")

    chapter = epub.EpubHtml(
        title="卷一",
        file_name="c0_gu_wang_yan.xhtml",
        uid="c0_gu_wang_yan",
        lang="zh",
    )
    chapter.set_content("<html><body><h1>卷一</h1><p>正文段落甲乙丙。</p></body></html>")
    book.add_item(chapter)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = [chapter]
    epub.write_epub(str(path), book)

    loaded = epub.read_epub(str(path))
    idref = loaded.spine[0][0]
    assert loaded.get_item_with_href(idref) is None
    assert loaded.get_item_with_id(idref) is not None
    assert loaded.get_item_with_id(idref).get_type() == ebooklib.ITEM_DOCUMENT


def test_load_epub_uses_spine_idref_not_href(tmp_path):
    p = tmp_path / "gu-wang-yan.epub"
    _write_epub_with_id_href_mismatch(p)
    text, meta = load_document(p, "epub")
    assert meta.get("title") == "姑妄言"
    assert meta.get("author") == "曹去晶"
    assert "正文段落甲乙丙" in text
    assert "§" in text


def test_load_epub_falls_back_when_spine_empty(tmp_path, monkeypatch):
    p = tmp_path / "no-spine.epub"
    _write_epub_with_id_href_mismatch(p)
    from ebooklib import epub as ebooklib_epub
    from lumina_core.ingest.epub import load_epub

    original_read = ebooklib_epub.read_epub

    def _read_empty_spine(path, *args, **kwargs):
        book = original_read(path, *args, **kwargs)
        book.spine = []
        return book

    monkeypatch.setattr(ebooklib_epub, "read_epub", _read_empty_spine)
    text, _meta = load_epub(p)
    assert "正文段落甲乙丙" in text
