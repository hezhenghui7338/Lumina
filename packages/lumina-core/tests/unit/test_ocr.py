"""OCR unit tests (mocked RapidOCR; optional deps not required)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from lumina_core import config
from lumina_core.ingest.ocr import (
    OcrDocumentResult,
    ocr_available,
    ocr_dependency_warning,
    ocr_install_hint,
    ocr_metadata_from_result,
    ocr_pdf,
)
from lumina_core.ingest.pdf import load_pdf
from lumina_core.main import smoke_ocr
from tests.support.ocr_helpers import fake_ocr_document, fake_ocr_pdf, write_blank_pdf, write_image_only_pdf


def _fake_ocr_pdf(_path: Path, **_kwargs) -> OcrDocumentResult:
    return fake_ocr_pdf(_path, **_kwargs)


def test_ocr_install_hint():
    assert "lumina-core[ocr]" in ocr_install_hint()
    assert "LUMINA_OCR_ENABLED=1" in ocr_install_hint(enabled=False)
    assert "pymupdf" in ocr_install_hint(enabled=True)


def test_ocr_install_hint_frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert "重新安装" in ocr_install_hint()
    assert "uv sync" not in ocr_install_hint()


def test_smoke_ocr_ok(monkeypatch):
    monkeypatch.setattr("lumina_core.ingest.ocr.ocr_dependency_warning", lambda: None)
    assert smoke_ocr() == 0


def test_smoke_ocr_reports_failure(monkeypatch):
    monkeypatch.setattr(
        "lumina_core.ingest.ocr.ocr_dependency_warning",
        lambda: "cv2 missing",
    )
    assert smoke_ocr() == 1


def test_ocr_dependency_warning_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "OCR_ENABLED", False)
    assert ocr_dependency_warning() is None
    assert ocr_available() is False


@pytest.mark.skipif(
    ocr_dependency_warning() is not None,
    reason=f"OCR deps unavailable: {ocr_dependency_warning() or ''}",
)
def test_ocr_pdf_on_image_only_page(tmp_path: Path):
    """Live OCR stack: image-only PDF should yield non-empty text."""
    pdf = tmp_path / "image-only.pdf"
    write_image_only_pdf(pdf, text="SCAN123")
    result = ocr_pdf(pdf)
    assert result.text.strip()
    assert result.pages
    normalized = result.text.upper()
    assert "SCAN" in normalized or "123" in normalized


@pytest.mark.skipif(
    ocr_dependency_warning() is not None,
    reason=f"OCR deps unavailable: {ocr_dependency_warning() or ''}",
)
def test_load_pdf_runs_real_ocr_on_image_only_page(tmp_path: Path):
    pdf = tmp_path / "scan-live.pdf"
    write_image_only_pdf(pdf, text="SCAN123")
    text, meta = load_pdf(pdf)
    assert meta.get("ocr_used") is True
    assert text.strip()
    normalized = text.upper()
    assert "SCAN" in normalized or "123" in normalized


def test_load_pdf_ocr_empty_result_raises(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "OCR_ENABLED", True)

    def empty_ocr(_path, **_kwargs):
        return OcrDocumentResult(text="", pages=[], avg_confidence=0.0)

    monkeypatch.setattr("lumina_core.ingest.pdf.ocr_pdf", empty_ocr)
    pdf = tmp_path / "scan.pdf"
    write_blank_pdf(pdf, pages=1)

    with pytest.raises(RuntimeError, match="OCR 失败或内容为空"):
        load_pdf(pdf)


def _empty_pdf(path: Path) -> None:
    write_blank_pdf(path)


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
    result = fake_ocr_document()
    meta = ocr_metadata_from_result(result)
    assert meta["ocr_used"] is True
    assert meta["ocr_pages"] == 2
    assert meta["ocr_confidence_avg"] == 0.92
