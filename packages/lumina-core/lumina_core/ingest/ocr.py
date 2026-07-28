"""OCR for scanned PDF — RapidOCR / PP-OCRv6 (optional extra)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

OCR_TEXT_COVERAGE_THRESHOLD = 0.15


def pdf_text_coverage(path: Path) -> float:
    """Estimate text-layer coverage ratio for a PDF."""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    if not reader.pages:
        return 0.0
    nonempty = 0
    for page in reader.pages:
        if (page.extract_text() or "").strip():
            nonempty += 1
    return nonempty / len(reader.pages)


def ocr_pdf(
    path: Path,
    *,
    on_progress: Callable[[int, int], None] | None = None,
) -> str:
    """Render pages and OCR. Requires lumina-core[ocr] extra."""
    try:
        import fitz  # PyMuPDF
        from rapidocr import RapidOCR
    except ImportError as e:
        raise RuntimeError(
            "OCR requires optional deps: uv sync --extra ocr (pymupdf, rapidocr)"
        ) from e

    ocr = RapidOCR()
    doc = fitz.open(str(path))
    parts: list[str] = []
    total = len(doc)
    for i, page in enumerate(doc, start=1):
        pix = page.get_pixmap(dpi=150)
        img_bytes = pix.tobytes("png")
        result, _ = ocr(img_bytes)
        lines = [line[1] for line in (result or [])]
        text = "\n".join(lines).strip()
        if text:
            parts.append(f"## [p.{i}]\n{text}")
        if on_progress:
            on_progress(i, total)
    doc.close()
    return "\n\n".join(parts)
