"""PDF text extraction via pypdf with optional OCR fallback."""

from __future__ import annotations

from pathlib import Path

from lumina_core.ingest.ocr import OCR_TEXT_COVERAGE_THRESHOLD, ocr_pdf, pdf_text_coverage


def load_pdf(path: Path, *, use_ocr: bool | None = None) -> tuple[str, dict]:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise RuntimeError("PDF support requires pypdf: pip install pypdf") from e

    reader = PdfReader(str(path))
    meta = reader.metadata or {}
    title = (meta.get("/Title") or meta.get("Title") or "").strip()
    author = (meta.get("/Author") or meta.get("Author") or "").strip()
    metadata = {"title": title or None, "author": author or None}

    coverage = pdf_text_coverage(path)
    metadata["text_coverage"] = coverage

    if use_ocr is None:
        use_ocr = coverage < OCR_TEXT_COVERAGE_THRESHOLD

    if use_ocr:
        try:
            text = ocr_pdf(path)
            metadata["ocr"] = True
            return text, metadata
        except RuntimeError:
            metadata["ocr"] = False

    parts: list[str] = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            parts.append(f"## [p.{i}]\n{text.strip()}")

    return "\n\n".join(parts), metadata
