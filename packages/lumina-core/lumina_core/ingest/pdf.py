"""PDF text extraction via pypdf with optional OCR fallback (LocalAgent-aligned)."""

from __future__ import annotations

from pathlib import Path

from lumina_core import config
from lumina_core.ingest.ocr import (
    OcrProgressCallback,
    ocr_install_hint,
    ocr_metadata_from_result,
    ocr_pdf,
)


def _pdf_needs_ocr(page_count: int, pages_with_text: int) -> bool:
    if page_count <= 0:
        return False
    if pages_with_text <= 0:
        return True
    return (pages_with_text / page_count) < config.OCR_PDF_TEXT_RATIO


def _merge_ocr_into_parts(parts: list[str], ocr_pages: dict[int, str]) -> str:
    merged: list[str] = []
    for part in parts:
        if part.startswith("## [p.") and "无文本]" in part:
            try:
                page_num = int(part.split("[p.")[1].split(" ")[0])
            except (IndexError, ValueError):
                merged.append(part)
                continue
            ocr_text = ocr_pages.get(page_num, "").strip()
            if ocr_text:
                merged.append(f"## [p.{page_num}]\n{ocr_text}")
            else:
                merged.append(part)
        else:
            merged.append(part)
    return "\n\n".join(merged)


def load_pdf(
    path: Path,
    *,
    use_ocr: bool | None = None,
    on_progress: OcrProgressCallback | None = None,
) -> tuple[str, dict]:
    """Extract text per page; OCR scanned PDFs when text layer is sparse/empty."""
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise RuntimeError("PDF support requires pypdf: pip install pypdf") from e

    reader = PdfReader(str(path))
    meta = reader.metadata or {}
    title = (meta.get("/Title") or meta.get("Title") or "").strip()
    author = (meta.get("/Author") or meta.get("Author") or "").strip()

    parts: list[str] = []
    page_count = len(reader.pages)
    pages_with_text = 0
    pages_failed: list[int] = []
    empty_page_nums: list[int] = []

    for index, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text() or ""
        except Exception:
            raw = ""
            pages_failed.append(index)

        text = raw.strip()
        if text:
            pages_with_text += 1
            parts.append(f"## [p.{index}]\n{text}")
        else:
            empty_page_nums.append(index)
            # Keep page marker so chunker preserves page order and coverage
            parts.append(f"## [p.{index} 无文本]")

    body = "\n\n".join(parts)
    coverage = (pages_with_text / page_count) if page_count else 0.0
    metadata: dict = {
        "title": title or None,
        "author": author or None,
        "page_count": page_count,
        "pages_with_text": pages_with_text,
        "text_coverage": coverage,
    }
    if pages_failed:
        metadata["pages_failed"] = pages_failed

    needs_ocr = _pdf_needs_ocr(page_count, pages_with_text)
    if use_ocr is None:
        should_ocr = needs_ocr
    else:
        should_ocr = use_ocr

    if not should_ocr:
        return body, metadata

    if not config.OCR_ENABLED:
        metadata["needs_ocr"] = True
        raise RuntimeError(f"扫描版 PDF 无文本层。{ocr_install_hint(enabled=False)}")

    try:
        if pages_with_text == 0 or not empty_page_nums:
            ocr_result = ocr_pdf(path, on_progress=on_progress)
            metadata.update(ocr_metadata_from_result(ocr_result))
            metadata["ocr"] = True
            if not ocr_result.text.strip():
                raise RuntimeError("扫描版 PDF OCR 失败或内容为空")
            return ocr_result.text, metadata

        ocr_result = ocr_pdf(path, page_nums=empty_page_nums, on_progress=on_progress)
        ocr_by_page = {page.page_num: page.text for page in ocr_result.pages}
        merged_body = _merge_ocr_into_parts(parts, ocr_by_page)
        metadata.update(ocr_metadata_from_result(ocr_result))
        metadata["ocr"] = True
        metadata["ocr_partial"] = True
        metadata["ocr_page_nums"] = empty_page_nums
        if not merged_body.strip():
            raise RuntimeError("扫描版 PDF OCR 失败或内容为空")
        return merged_body, metadata
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"扫描版 PDF OCR 失败: {exc}") from exc
