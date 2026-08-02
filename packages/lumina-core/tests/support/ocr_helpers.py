"""Shared OCR test fixtures (mock + image-only PDF for live OCR)."""

from __future__ import annotations

from pathlib import Path

from lumina_core.ingest.ocr import OcrDocumentResult, OcrPageResult


def write_blank_pdf(path: Path, *, pages: int = 2) -> None:
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    with path.open("wb") as handle:
        writer.write(handle)


def write_image_only_pdf(path: Path, text: str = "SCAN123") -> None:
    """PDF page with raster text only (no extractable text layer)."""
    fitz = __import__("fitz")
    src = fitz.open()
    try:
        src_page = src.new_page(width=640, height=200)
        src_page.insert_text((72, 120), text, fontsize=48)
        pix = src_page.get_pixmap(dpi=200)
        doc = fitz.open()
        try:
            page = doc.new_page(width=pix.width, height=pix.height)
            page.insert_image(page.rect, pixmap=pix)
            doc.save(str(path))
        finally:
            doc.close()
    finally:
        src.close()


def fake_ocr_document(
    *,
    pages: list[tuple[int, str]] | None = None,
) -> OcrDocumentResult:
    if pages is None:
        pages = [(1, "扫描页一"), (2, "扫描页二")]
    page_results = [
        OcrPageResult(page_num=num, text=body, avg_confidence=0.92, low_confidence=False)
        for num, body in pages
    ]
    sections = [f"## [p.{num}]\n{body}" for num, body in pages]
    confidences = [page.avg_confidence for page in page_results]
    avg = sum(confidences) / len(confidences) if confidences else 0.0
    return OcrDocumentResult(
        text="\n\n".join(sections),
        pages=page_results,
        avg_confidence=avg,
        warnings=[],
    )


def fake_ocr_pdf(_path: Path, **_kwargs) -> OcrDocumentResult:
    page_nums = _kwargs.get("page_nums")
    if page_nums:
        pages = [(num, f"扫描页{num}") for num in page_nums[:1]]
        return fake_ocr_document(pages=pages)
    return fake_ocr_document()
