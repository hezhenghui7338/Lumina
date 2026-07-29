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
