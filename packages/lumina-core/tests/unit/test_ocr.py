"""OCR unit tests (mocked RapidOCR; optional deps not required)."""

from __future__ import annotations

from pathlib import Path

import pytest

from lumina_core import config
from lumina_core.ingest.ocr import (
    OcrDocumentResult,
    OcrPageResult,
    ocr_install_hint,
    ocr_metadata_from_result,
    ocr_pdf,
)
from lumina_core.ingest.pdf import load_pdf


def _empty_pdf(path: Path) -> None:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_blank_page(width=200, height=200)
    with path.open("wb") as handle:
        writer.write(handle)


def _fake_ocr_pdf(_path: Path, **_kwargs) -> OcrDocumentResult:
    return OcrDocumentResult(
        text="## [p.1]\n扫描页一\n\n## [p.2]\n扫描页二",
        pages=[
            OcrPageResult(page_num=1, text="扫描页一", avg_confidence=0.95, low_confidence=False),
            OcrPageResult(page_num=2, text="扫描页二", avg_confidence=0.88, low_confidence=False),
        ],
        avg_confidence=0.915,
        warnings=[],
    )


def test_ocr_install_hint():
    assert "lumina-core[ocr]" in ocr_install_hint()
    assert "LUMINA_OCR_ENABLED=1" in ocr_install_hint(enabled=False)
    assert "pymupdf" in ocr_install_hint(enabled=True)


def _block_fitz_import(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "fitz":
            raise ImportError("No module named 'fitz'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_ocr_pdf_missing_fitz_raises(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "OCR_ENABLED", True)
    monkeypatch.setattr(
        "lumina_core.ingest.ocr._ensure_engine",
        lambda: object(),
    )
    pdf = tmp_path / "scan.pdf"
    _empty_pdf(pdf)
    _block_fitz_import(monkeypatch)

    with pytest.raises(RuntimeError, match="PyMuPDF missing"):
        ocr_pdf(pdf)


def test_load_scanned_pdf_with_mock_ocr(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "OCR_ENABLED", True)
    monkeypatch.setattr("lumina_core.ingest.pdf.ocr_pdf", _fake_ocr_pdf)
    pdf = tmp_path / "scan.pdf"
    _empty_pdf(pdf)

    text, meta = load_pdf(pdf)
    assert "扫描页一" in text
    assert meta.get("ocr_used") is True
    assert meta.get("ocr") is True
    assert "## [p.1]" in text


def test_load_scanned_pdf_ocr_disabled(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "OCR_ENABLED", False)
    pdf = tmp_path / "scan.pdf"
    _empty_pdf(pdf)

    with pytest.raises(RuntimeError, match="扫描版 PDF 无文本层"):
        load_pdf(pdf)


def test_load_scanned_pdf_missing_deps(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "OCR_ENABLED", True)
    pdf = tmp_path / "scan.pdf"
    _empty_pdf(pdf)

    def boom(_path, **_kwargs):
        raise RuntimeError(f"OCR dependencies missing. {ocr_install_hint()}")

    monkeypatch.setattr("lumina_core.ingest.pdf.ocr_pdf", boom)
    with pytest.raises(RuntimeError, match="OCR dependencies missing"):
        load_pdf(pdf)


def test_ocr_metadata_from_result():
    result = _fake_ocr_pdf(Path("x.pdf"))
    meta = ocr_metadata_from_result(result)
    assert meta["ocr_used"] is True
    assert meta["ocr_pages"] == 2
    assert meta["ocr_confidence_avg"] == 0.915
