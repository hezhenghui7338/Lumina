"""Local OCR via RapidOCR (PP-OCRv6) for scanned PDFs — algorithm aligned with LocalAgent."""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from lumina_core import config

logger = logging.getLogger(__name__)

OcrProgressCallback = Callable[[int, int, str], None]

_ENGINE = None
_OCR_EXTRA = "lumina-core[ocr]"


@dataclass
class OcrPageResult:
    page_num: int
    text: str
    avg_confidence: float
    low_confidence: bool


@dataclass
class OcrDocumentResult:
    text: str
    pages: list[OcrPageResult] = field(default_factory=list)
    avg_confidence: float = 0.0
    engine: str = "rapidocr/pp-ocrv6"
    warnings: list[str] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.pages)


def ocr_install_hint(*, enabled: bool | None = None) -> str:
    ocr_on = config.OCR_ENABLED if enabled is None else enabled
    if getattr(sys, "frozen", False):
        return "请重新安装完整的 Lumina 安装包；若问题仍在，请联系维护者。"
    install = f"uv sync --extra ocr  # or: pip install '{_OCR_EXTRA}'"
    if ocr_on:
        return f"请安装 OCR 可选依赖（rapidocr、onnxruntime、pymupdf）：{install}"
    return f"启用本地 OCR：{install} 并设置 LUMINA_OCR_ENABLED=1"


def _ensure_fitz() -> None:
    try:
        import fitz  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(f"PyMuPDF missing ({exc}). {ocr_install_hint()}") from exc


def ocr_available() -> bool:
    """Return True when OCR is enabled and optional deps import cleanly."""
    return ocr_dependency_warning() is None and config.OCR_ENABLED


def ocr_dependency_warning() -> str | None:
    """Return a user-facing warning when OCR is enabled but deps are incomplete."""
    if not config.OCR_ENABLED:
        return None
    try:
        _ensure_engine()
    except RuntimeError as exc:
        return str(exc)
    try:
        _ensure_fitz()
    except RuntimeError as exc:
        return str(exc)
    return None


def _tier_model_type():
    from rapidocr import ModelType

    tier = (config.OCR_TIER or "medium").strip().lower()
    mapping = {
        "tiny": ModelType.TINY,
        "small": ModelType.SMALL,
        "medium": ModelType.MEDIUM,
    }
    if tier not in mapping:
        raise RuntimeError(f"invalid LUMINA_OCR_TIER {tier!r}; expected tiny|small|medium")
    return mapping[tier]


def _ensure_engine():
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    if not config.OCR_ENABLED:
        raise RuntimeError(f"OCR disabled (LUMINA_OCR_ENABLED=0). {ocr_install_hint()}")
    try:
        from rapidocr import OCRVersion, RapidOCR
    except ImportError as exc:
        raise RuntimeError(
            f"OCR dependencies missing ({exc}). {ocr_install_hint()}"
        ) from exc

    model_type = _tier_model_type()
    tier = (config.OCR_TIER or "medium").strip().lower()
    try:
        _ENGINE = RapidOCR(
            params={
                "Det.model_type": model_type,
                "Det.ocr_version": OCRVersion.PPOCRV6,
                "Det.lang_type": config.OCR_LANG,
                "Rec.model_type": model_type,
                "Rec.ocr_version": OCRVersion.PPOCRV6,
                "Rec.lang_type": config.OCR_LANG,
            }
        )
    except Exception as exc:
        detail = str(exc)
        lower = detail.lower()
        if "failed to download" in lower or "downloadfile" in lower:
            raise RuntimeError(
                "OCR 模型未内置或无法从 modelscope 下载。"
                "请使用完整 release 包，或检查网络后重试："
                f" {detail}"
            ) from exc
        raise RuntimeError(f"OCR 引擎初始化失败: {detail}") from exc
    logger.info("OCR engine ready (PP-OCRv6 %s, lang=%s)", tier, config.OCR_LANG)
    return _ENGINE


def _format_page_section(page_num: int, text: str) -> str:
    body = text.strip()
    if not body:
        return ""
    return f"## [p.{page_num}]\n{body}"


def _lines_from_ocr_output(result) -> tuple[list[str], list[float]]:
    txts = list(getattr(result, "txts", None) or ())
    scores = list(getattr(result, "scores", None) or ())
    if not txts:
        return [], []
    if len(scores) < len(txts):
        scores.extend([0.0] * (len(txts) - len(scores)))
    return [str(t).strip() for t in txts if str(t).strip()], [float(s) for s in scores[: len(txts)]]


def _run_image_ocr(engine, image) -> tuple[str, float]:
    output = engine(image, use_det=True, use_cls=True, use_rec=True)
    if output is None:
        return "", 0.0
    lines, scores = _lines_from_ocr_output(output)
    if not lines:
        return "", 0.0
    text = "\n".join(lines)
    avg = sum(scores) / len(scores) if scores else 0.0
    return text, avg


def ocr_pdf(
    path: Path,
    *,
    dpi: int | None = None,
    page_nums: list[int] | None = None,
    on_progress: OcrProgressCallback | None = None,
) -> OcrDocumentResult:
    """Render each PDF page and OCR it. Optionally limit to 1-based page_nums."""
    path = Path(path)
    if not path.is_file():
        raise RuntimeError(f"PDF not found: {path}")

    _ensure_fitz()
    engine = _ensure_engine()

    import fitz
    import numpy as np

    render_dpi = dpi if dpi is not None else config.OCR_PDF_DPI

    doc = fitz.open(str(path))
    try:
        doc_page_count = doc.page_count
        if page_nums:
            targets = sorted({n for n in page_nums if 1 <= n <= doc_page_count})
        else:
            targets = list(range(1, doc_page_count + 1))
        total = len(targets)
        pages: list[OcrPageResult] = []
        sections: list[str] = []
        confidences: list[float] = []
        warnings: list[str] = []

        for progress_idx, page_num in enumerate(targets, start=1):
            if on_progress:
                on_progress(
                    progress_idx,
                    total,
                    f"扫描版 PDF · 正在识别 {progress_idx}/{total} 页…",
                )
            page = doc.load_page(page_num - 1)
            pix = page.get_pixmap(dpi=render_dpi, alpha=False)
            samples = memoryview(pix.samples)
            image = np.frombuffer(samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            if pix.n == 4:
                image = image[:, :, :3]

            text, avg = _run_image_ocr(engine, image)
            confidences.append(avg)
            low = avg < config.OCR_MIN_CONF and bool(text)
            if low:
                warnings.append(
                    f"p.{page_num} OCR 置信度偏低 ({avg:.2f})，建议人工核对原文"
                )
            pages.append(
                OcrPageResult(
                    page_num=page_num,
                    text=text,
                    avg_confidence=avg,
                    low_confidence=low,
                )
            )
            section = _format_page_section(page_num, text)
            if section:
                sections.append(section)
    finally:
        doc.close()

    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
    return OcrDocumentResult(
        text="\n\n".join(sections),
        pages=pages,
        avg_confidence=avg_conf,
        warnings=warnings,
    )


def ocr_pdf_pages(
    path: Path,
    page_nums: list[int],
    *,
    dpi: int | None = None,
    on_progress: OcrProgressCallback | None = None,
) -> OcrDocumentResult:
    """OCR a subset of pages (1-based indices)."""
    return ocr_pdf(path, dpi=dpi, page_nums=page_nums, on_progress=on_progress)


def ocr_metadata_from_result(result: OcrDocumentResult) -> dict:
    """Map OCR output into load_pdf metadata keys."""
    return {
        "ocr_used": True,
        "ocr_engine": result.engine,
        "ocr_confidence_avg": round(result.avg_confidence, 4),
        "ocr_pages": result.page_count,
        "ocr_warnings": list(result.warnings),
        "page_count": result.page_count,
        "pages_with_text": sum(1 for page in result.pages if page.text.strip()),
    }


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
