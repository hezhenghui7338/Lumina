"""PDF text extraction via PyMuPDF (preferred) or pypdf, with OCR fallback."""

from __future__ import annotations

import threading
import unicodedata
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from lumina_core import config
from lumina_core.chunker.roles import classify_heading
from lumina_core.config import Settings
from lumina_core.ingest.ocr import (
    ocr_cloud_configured,
    ocr_install_hint,
    ocr_metadata_from_result,
    ocr_pdf,
)
from lumina_core.ingest.progress import (
    DocumentLoadCancelled,
    OcrProgressCallback,
    check_cancel,
    report_progress,
    yield_ui,
)

try:
    from pypdf import PdfReader as _PdfReader
except ImportError:
    _PdfReader = None  # type: ignore[misc, assignment]

_PDF_PROBE_MAX = 16
_CID_TOKEN = "(cid:"
# Identity-H CJK without ToUnicode scatters into many rare scripts. Latin / CJK /
# Greek / Hangul / Cyrillic / Arabic stay "core" so English, 中文, STEM, 俄语, 韩语
# pages are not treated as broken just because they mix a second script.
_CORE_SCRIPTS = {
    "LATIN",
    "CJK",
    "GREEK",
    "HIRAGANA",
    "KATAKANA",
    "HANGUL",
    "CYRILLIC",
    "ARABIC",
    "HEBREW",
    "THAI",
}


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


def _probe_page_indices(page_count: int) -> list[int]:
    """Spread sample pages so a scanned PDF does not extract every page first."""
    if page_count <= _PDF_PROBE_MAX:
        return list(range(1, page_count + 1))
    chosen = {1, 2, page_count}
    remaining = _PDF_PROBE_MAX - len(chosen)
    for step in range(1, remaining + 1):
        idx = 1 + round(step * (page_count - 1) / (remaining + 1))
        chosen.add(max(1, min(page_count, int(idx))))
    return sorted(chosen)


def _letter_script(ch: str) -> str | None:
    if not unicodedata.category(ch).startswith("L"):
        return None
    name = unicodedata.name(ch, "")
    if name.startswith("CJK"):
        return "CJK"
    if name:
        return name.split()[0]
    code = ord(ch)
    if 0xE000 <= code <= 0xF8FF:
        return "PUA"
    return "OTHER"


def text_layer_garbled(text: str) -> bool:
    """True when a PDF text layer is CID/Identity-H mojibake, not real copy."""
    if _CID_TOKEN in text.lower():
        return True
    if text.count("\ufffd") >= 3:
        return True
    scripts = [_letter_script(ch) for ch in text]
    letters = [script for script in scripts if script]
    if len(letters) < 40:
        return False
    counts = Counter(letters)
    if counts.get("CJK", 0) / len(letters) >= 0.12:
        return False
    scatter = sum(
        1 for script, n in counts.items() if script not in _CORE_SCRIPTS and n >= 2
    )
    if scatter >= 4:
        return True
    rare = sum(n for script, n in counts.items() if script not in _CORE_SCRIPTS)
    return scatter >= 3 and rare / len(letters) >= 0.15


def _page_text(page) -> str:
    """Extract one page; isolated so tests can count calls."""
    extract = getattr(page, "extract_text", None)
    if callable(extract):
        return extract() or ""
    get_text = getattr(page, "get_text", None)
    if callable(get_text):
        return get_text("text") or ""
    return ""


def _outline_titles_by_page(reader) -> dict[int, str]:
    """First outline title per 1-based page number, if the PDF has bookmarks."""
    titles: dict[int, str] = {}
    outline = getattr(reader, "outline", None)
    if not outline:
        return titles

    def walk(entries) -> None:
        if not entries:
            return
        for entry in entries:
            if isinstance(entry, list):
                walk(entry)
                continue
            try:
                page = reader.get_destination_page_number(entry)
            except Exception:
                continue
            title = str(getattr(entry, "title", "") or "").strip()
            if page is None or not title:
                continue
            titles.setdefault(int(page) + 1, title)

    try:
        walk(outline)
    except Exception:
        return titles
    return titles


def _outline_titles_from_fitz(doc) -> dict[int, str]:
    titles: dict[int, str] = {}
    try:
        toc = doc.get_toc() or []
    except Exception:
        return titles
    for entry in toc:
        if not isinstance(entry, (list, tuple)) or len(entry) < 3:
            continue
        title = str(entry[1] or "").strip()
        try:
            page = int(entry[2])
        except (TypeError, ValueError):
            continue
        if title and page >= 1:
            titles.setdefault(page, title)
    return titles


def _open_fitz(path: Path):
    """Open with PyMuPDF when installed; Identity-H CID fonts decode correctly."""
    try:
        import fitz
    except ImportError:
        return None
    try:
        return fitz.open(str(path))
    except Exception:
        return None


def load_pdf(
    path: Path,
    *,
    use_ocr: bool | None = None,
    on_progress: OcrProgressCallback | None = None,
    settings: Settings | None = None,
    cancel_event: threading.Event | None = None,
) -> tuple[str, dict]:
    """Extract text per page; OCR scanned PDFs when text layer is sparse/empty."""
    report_progress(on_progress, 0, 0, "正在打开 PDF…", cancel_event)
    doc = _open_fitz(path)
    if doc is not None:
        try:
            meta = doc.metadata or {}
            return _extract_pdf_pages(
                path,
                page_count=doc.page_count,
                load_page=doc.load_page,
                title=(meta.get("title") or "").strip(),
                author=(meta.get("author") or "").strip(),
                outline_titles=_outline_titles_from_fitz(doc),
                extractor="pymupdf",
                use_ocr=use_ocr,
                on_progress=on_progress,
                settings=settings,
                cancel_event=cancel_event,
            )
        finally:
            doc.close()

    if _PdfReader is None:
        raise RuntimeError("PDF support requires pypdf: pip install pypdf")

    reader = _PdfReader(str(path))
    meta = reader.metadata or {}
    return _extract_pdf_pages(
        path,
        page_count=len(reader.pages),
        load_page=lambda index: reader.pages[index],
        title=(meta.get("/Title") or meta.get("Title") or "").strip(),
        author=(meta.get("/Author") or meta.get("Author") or "").strip(),
        outline_titles=_outline_titles_by_page(reader),
        extractor="pypdf",
        use_ocr=use_ocr,
        on_progress=on_progress,
        settings=settings,
        cancel_event=cancel_event,
    )


def _extract_pdf_pages(
    path: Path,
    *,
    page_count: int,
    load_page: Callable[[int], object],
    title: str,
    author: str,
    outline_titles: dict[int, str],
    extractor: str,
    use_ocr: bool | None,
    on_progress: OcrProgressCallback | None,
    settings: Settings | None,
    cancel_event: threading.Event | None,
) -> tuple[str, dict]:
    yield_ui()
    parts: list[str | None] = [None] * page_count
    pages_with_text = 0
    pages_failed: list[int] = []
    empty_page_nums: list[int] = []
    garbled_page_nums: list[int] = []
    extracted: set[int] = set()
    structure_roles: list[dict] = []
    seen_outline_titles: set[str] = set()

    def _page_block(index: int, body: str) -> str:
        heading = outline_titles.get(index)
        marker = f"## [p.{index}]\n{body}" if body else f"## [p.{index} 无文本]"
        if not heading:
            return marker
        if heading not in seen_outline_titles:
            seen_outline_titles.add(heading)
            structure_roles.append(
                {"title": heading, "role": classify_heading(heading).value}
            )
        return f"## [§{heading}]\n{marker}"

    def extract_index(index: int) -> None:
        nonlocal pages_with_text
        if index in extracted:
            return
        check_cancel(cancel_event)
        try:
            raw = _page_text(load_page(index - 1))
        except DocumentLoadCancelled:
            raise
        except Exception:
            raw = ""
            pages_failed.append(index)
        stripped = (raw or "").strip()
        if stripped and text_layer_garbled(stripped):
            garbled_page_nums.append(index)
            text = ""
        else:
            text = stripped
        if text:
            pages_with_text += 1
            parts[index - 1] = _page_block(index, text)
        else:
            empty_page_nums.append(index)
            parts[index - 1] = _page_block(index, "")
        extracted.add(index)
        yield_ui()

    probe = _probe_page_indices(page_count)
    for pos, index in enumerate(probe, start=1):
        report_progress(
            on_progress,
            pos,
            len(probe),
            f"正在检查 PDF 文本层 {pos}/{len(probe)}…",
            cancel_event,
        )
        extract_index(index)

    probe_empty = {idx for idx in probe if idx in empty_page_nums}
    scanned_probe = _pdf_needs_ocr(len(probe), len(probe) - len(probe_empty))

    remaining = [index for index in range(1, page_count + 1) if index not in extracted]
    if remaining and not scanned_probe:
        for pos, index in enumerate(remaining, start=1):
            report_progress(
                on_progress,
                len(probe) + pos,
                page_count,
                f"正在提取 PDF 文本 {index}/{page_count}…",
                cancel_event,
            )
            extract_index(index)
    elif remaining:
        for index in remaining:
            check_cancel(cancel_event)
            empty_page_nums.append(index)
            parts[index - 1] = f"## [p.{index} 无文本]"
            extracted.add(index)

    filled_parts = [part or f"## [p.{i} 无文本]" for i, part in enumerate(parts, start=1)]
    body = "\n\n".join(filled_parts)
    coverage = (pages_with_text / page_count) if page_count else 0.0
    metadata: dict = {
        "title": title or None,
        "author": author or None,
        "page_count": page_count,
        "pages_with_text": pages_with_text,
        "text_coverage": coverage,
        "pdf_extractor": extractor,
    }
    if pages_failed:
        metadata["pages_failed"] = pages_failed
    if garbled_page_nums:
        metadata["text_layer_garbled_pages"] = garbled_page_nums
    if structure_roles:
        metadata["structure_roles"] = structure_roles
    if remaining and scanned_probe:
        metadata["text_layer_probed"] = True
        metadata["text_layer_probe_pages"] = len(probe)

    needs_ocr = _pdf_needs_ocr(page_count, pages_with_text) or (
        bool(remaining) and scanned_probe
    )
    if use_ocr is None:
        should_ocr = needs_ocr
    else:
        should_ocr = use_ocr

    if not should_ocr:
        return body, metadata

    runtime_settings = settings or Settings()
    if not config.OCR_ENABLED and not ocr_cloud_configured(runtime_settings):
        metadata["needs_ocr"] = True
        raise RuntimeError(f"扫描版 PDF 无文本层。{ocr_install_hint(enabled=False)}")

    try:
        ocr_kwargs = {
            "on_progress": on_progress,
            "settings": runtime_settings,
            "cancel_event": cancel_event,
        }
        if pages_with_text == 0 or not empty_page_nums:
            ocr_result = ocr_pdf(path, **ocr_kwargs)
            metadata.update(ocr_metadata_from_result(ocr_result))
            metadata["ocr"] = True
            if not ocr_result.text.strip():
                raise RuntimeError("扫描版 PDF OCR 失败或内容为空")
            return ocr_result.text, metadata

        ocr_result = ocr_pdf(path, page_nums=empty_page_nums, **ocr_kwargs)
        ocr_by_page = {page.page_num: page.text for page in ocr_result.pages}
        merged_body = _merge_ocr_into_parts(filled_parts, ocr_by_page)
        metadata.update(ocr_metadata_from_result(ocr_result))
        metadata["ocr"] = True
        metadata["ocr_partial"] = True
        metadata["ocr_page_nums"] = empty_page_nums
        if not merged_body.strip():
            raise RuntimeError("扫描版 PDF OCR 失败或内容为空")
        return merged_body, metadata
    except DocumentLoadCancelled:
        raise
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"扫描版 PDF OCR 失败: {exc}") from exc
