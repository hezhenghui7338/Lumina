"""Local and OpenAI-compatible cloud OCR for scanned PDFs."""

from __future__ import annotations

import base64
import logging
import sys
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from lumina_core import config
from lumina_core.config import Settings
from lumina_core.ingest.progress import DocumentLoadCancelled, report_progress, yield_ui
from lumina_core.models.openai_compat import openai_compat_completions_url

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


def ocr_cloud_configured(settings: Settings) -> bool:
    return bool(
        settings.ocr_cloud_base_url.strip()
        and settings.ocr_cloud_model.strip()
        and (settings.ocr_cloud_api_key or "").strip()
    )


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


_PAGE_OCR_ERROR = "（本页识别出错）"


def _format_page_section(page_num: int, text: str) -> str:
    body = text.strip() or _PAGE_OCR_ERROR
    return f"## [p.{page_num}]\n{body}"


def _finish_pages(pages: list[OcrPageResult]) -> str:
    """Keep every OCR page. Blank or failed pages stay in the book with an error note."""
    chunks: list[str] = []
    for page in pages:
        body = page.text.strip() or _PAGE_OCR_ERROR
        page.text = body
        chunks.append(f"## [p.{page.page_num}]\n{body}")
    return "\n\n".join(chunks)


def ocr_result_text(result: OcrDocumentResult) -> str:
    """Join page text. Empty pages become an in-book error note instead of dropping the book."""
    if result.pages:
        return _finish_pages(result.pages)
    return result.text


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


def _ocr_pdf_local(
    path: Path,
    *,
    dpi: int | None = None,
    page_nums: list[int] | None = None,
    on_progress: OcrProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> OcrDocumentResult:
    """Render each PDF page and OCR it locally with RapidOCR."""
    path = Path(path)
    if not path.is_file():
        raise RuntimeError(f"PDF not found: {path}")

    _ensure_fitz()
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
        report_progress(
            on_progress, 0, total, "正在加载 OCR 引擎…", cancel_event
        )
        engine = _ensure_engine()
        yield_ui()
        pages: list[OcrPageResult] = []
        sections: list[str] = []
        confidences: list[float] = []
        warnings: list[str] = []

        for progress_idx, page_num in enumerate(targets, start=1):
            report_progress(
                on_progress,
                progress_idx,
                total,
                f"扫描版 PDF · 本地 OCR {progress_idx}/{total} 页…",
                cancel_event,
            )
            image = None
            try:
                page = doc.load_page(page_num - 1)
                pix = page.get_pixmap(dpi=render_dpi, alpha=False)
                samples = memoryview(pix.samples)
                image = np.frombuffer(samples, dtype=np.uint8).reshape(
                    pix.height, pix.width, pix.n
                )
                if pix.n == 4:
                    image = image[:, :, :3].copy()
                else:
                    image = image.copy()
                del pix
                text, avg = _run_image_ocr(engine, image)
            except DocumentLoadCancelled:
                raise
            except Exception as exc:
                warnings.append(f"p.{page_num} 本地 OCR 失败，已跳过：{exc}")
                pages.append(
                    OcrPageResult(
                        page_num=page_num,
                        text="",
                        avg_confidence=0.0,
                        low_confidence=False,
                    )
                )
                continue
            finally:
                del image
            yield_ui()
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
        text=_finish_pages(pages),
        pages=pages,
        avg_confidence=avg_conf,
        engine="rapidocr/pp-ocrv6",
        warnings=warnings,
    )


_CLOUD_OCR_PROMPT = """你是 OCR 引擎。请逐字识别图片中的全部文字。
要求：
1. 只输出识别出的正文，不要解释、总结或添加前后缀。
2. 保留自然段、标题、列表和表格的阅读顺序。
3. 不确定的字符按最可能结果输出，不要编造图片中不存在的内容。
4. 如果图片确实没有文字，输出空字符串。"""


def _cloud_text(payload: dict) -> str:
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("云端 OCR 返回格式无效：缺少 choices[0].message.content") from exc
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "\n".join(
            str(item.get("text") or "")
            for item in content
            if isinstance(item, dict) and item.get("type") in {"text", "output_text"}
        )
    else:
        raise TypeError("云端 OCR 返回格式无效：content 不是文本")
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2:
            stripped = "\n".join(lines[1:-1]).strip()
    return stripped


def _image_media_type(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _cloud_request(client: httpx.Client, *, model: str, image_bytes: bytes) -> str:
    image_data = base64.b64encode(image_bytes).decode("ascii")
    media_type = _image_media_type(image_bytes)
    response = client.post(
        openai_compat_completions_url(str(client.base_url)),
        json={
            "model": model,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _CLOUD_OCR_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{media_type};base64,{image_data}"},
                        },
                    ],
                }
            ],
        },
    )
    if response.status_code == 401:
        raise RuntimeError("云端 OCR API Key 无效或未授权")
    if response.status_code == 429:
        raise RuntimeError("云端 OCR 请求受限或额度不足（HTTP 429）")
    if response.status_code >= 400:
        raise RuntimeError(f"云端 OCR 请求失败（HTTP {response.status_code}）")
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("云端 OCR 返回了无效 JSON") from exc
    return _cloud_text(payload)


# First request plus three retries. After that, this page and the rest of the book use local OCR.
_CLOUD_OCR_EXTRA_RETRIES = 3


@dataclass
class _OcrRoute:
    cloud: bool = True
    used_cloud: bool = False
    used_local: bool = False


def _describe_cloud_failure(exc: BaseException, *, base_url: str) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return f"云端 OCR 请求超时 ({type(exc).__name__}: {exc})"
    if isinstance(exc, httpx.ConnectError):
        return f"无法连接云端 OCR：{base_url}"
    if isinstance(exc, httpx.HTTPError):
        return f"云端 OCR 网络请求失败：{type(exc).__name__}"
    text = str(exc).strip() or type(exc).__name__
    return text


def _engine_name(route: _OcrRoute, model: str) -> str:
    cloud_name = f"openai-compatible/{model}"
    local_name = "rapidocr/pp-ocrv6"
    if route.used_cloud and route.used_local:
        return f"{cloud_name}+{local_name}"
    if route.used_local:
        return local_name
    return cloud_name


def _ocr_encoded_image_local(image_bytes: bytes) -> tuple[str, float]:
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(f"OCR image dependencies missing ({exc}). {ocr_install_hint()}") from exc
    encoded = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("图片无法解码")
    try:
        return _run_image_ocr(_ensure_engine(), image)
    finally:
        del image


def _recognize_page(
    *,
    page_num: int,
    image_bytes: bytes,
    client: httpx.Client,
    model: str,
    base_url: str,
    route: _OcrRoute,
    warnings: list[str],
    on_progress: OcrProgressCallback | None,
    progress_idx: int,
    total: int,
    kind_label: str,
    cancel_event: threading.Event | None,
) -> tuple[str, float, bool]:
    """Return page text, confidence, and whether this page used local OCR."""
    if route.cloud:
        last_reason = "云端 OCR 请求失败"
        attempts = 1 + _CLOUD_OCR_EXTRA_RETRIES
        for attempt in range(attempts):
            retry = ""
            if attempt:
                retry = f"（重试 {attempt}/{_CLOUD_OCR_EXTRA_RETRIES}）"
            report_progress(
                on_progress,
                progress_idx,
                total,
                f"{kind_label} · 云端 OCR {progress_idx}/{total} 页{retry}…",
                cancel_event,
            )
            try:
                text = _cloud_request(client, model=model, image_bytes=image_bytes)
            except DocumentLoadCancelled:
                raise
            except Exception as exc:
                last_reason = _describe_cloud_failure(exc, base_url=base_url)
                logger.warning(
                    "cloud OCR p.%s attempt %s/%s failed: %s",
                    page_num,
                    attempt + 1,
                    attempts,
                    last_reason,
                )
                continue
            route.used_cloud = True
            return text, (1.0 if text else 0.0), False
        route.cloud = False
        warnings.append(
            f"云端 OCR 在 p.{page_num} 失败（已重试 {_CLOUD_OCR_EXTRA_RETRIES} 次：{last_reason}），自该页起改用本地"
        )
    report_progress(
        on_progress,
        progress_idx,
        total,
        f"{kind_label} · 本地 OCR {progress_idx}/{total} 页…",
        cancel_event,
    )
    try:
        text, avg = _ocr_encoded_image_local(image_bytes)
    except DocumentLoadCancelled:
        raise
    except Exception as exc:
        warnings.append(f"p.{page_num} 本地 OCR 失败，已跳过：{exc}")
        return "", 0.0, True
    route.used_local = True
    return text, avg, True


def _ocr_images_local(
    images: Iterable[tuple[int, bytes]],
    *,
    total: int,
    on_progress: OcrProgressCallback | None,
    cancel_event: threading.Event | None,
) -> OcrDocumentResult:
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(f"OCR image dependencies missing ({exc}). {ocr_install_hint()}") from exc

    report_progress(on_progress, 0, total, "正在加载 OCR 引擎…", cancel_event)
    engine = _ensure_engine()
    pages: list[OcrPageResult] = []
    sections: list[str] = []
    confidences: list[float] = []
    warnings: list[str] = []
    for progress_idx, (page_num, image_bytes) in enumerate(images, start=1):
        report_progress(
            on_progress,
            progress_idx,
            total,
            f"图片型 EPUB · 本地 OCR {progress_idx}/{total} 页…",
            cancel_event,
        )
        encoded = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if image is None:
            warnings.append(f"p.{page_num} 图片无法解码，已跳过")
            pages.append(OcrPageResult(page_num, "", 0.0, False))
            continue
        try:
            text, avg = _run_image_ocr(engine, image)
        except DocumentLoadCancelled:
            raise
        except Exception as exc:
            warnings.append(f"p.{page_num} 本地 OCR 失败，已跳过：{exc}")
            pages.append(OcrPageResult(page_num, "", 0.0, False))
            continue
        finally:
            del image
        yield_ui()
        confidences.append(avg)
        low = avg < config.OCR_MIN_CONF and bool(text)
        if low:
            warnings.append(f"p.{page_num} OCR 置信度偏低 ({avg:.2f})，建议人工核对原文")
        pages.append(OcrPageResult(page_num, text, avg, low))
        section = _format_page_section(page_num, text)
        if section:
            sections.append(section)
    return OcrDocumentResult(
        text=_finish_pages(pages),
        pages=pages,
        avg_confidence=sum(confidences) / len(confidences) if confidences else 0.0,
        engine="rapidocr/pp-ocrv6",
        warnings=warnings,
    )


def _ocr_images_cloud(
    images: Iterable[tuple[int, bytes]],
    *,
    total: int,
    settings: Settings,
    on_progress: OcrProgressCallback | None,
    cancel_event: threading.Event | None,
) -> OcrDocumentResult:
    base_url = settings.ocr_cloud_base_url.strip()
    model = settings.ocr_cloud_model.strip()
    headers = {"Authorization": f"Bearer {(settings.ocr_cloud_api_key or '').strip()}"}
    pages: list[OcrPageResult] = []
    warnings: list[str] = []
    route = _OcrRoute()
    with httpx.Client(
        base_url=base_url.rstrip("/") + "/",
        headers=headers,
        timeout=settings.ocr_cloud_timeout_seconds,
    ) as client:
        for progress_idx, (page_num, image_bytes) in enumerate(images, start=1):
            text, avg, from_local = _recognize_page(
                page_num=page_num,
                image_bytes=image_bytes,
                client=client,
                model=model,
                base_url=base_url,
                route=route,
                warnings=warnings,
                on_progress=on_progress,
                progress_idx=progress_idx,
                total=total,
                kind_label="图片型 EPUB",
                cancel_event=cancel_event,
            )
            low = from_local and avg < config.OCR_MIN_CONF and bool(text)
            if low:
                warnings.append(f"p.{page_num} OCR 置信度偏低 ({avg:.2f})，建议人工核对原文")
            pages.append(OcrPageResult(page_num, text, avg, low))
    nonempty = [page.avg_confidence for page in pages if page.text.strip()]
    return OcrDocumentResult(
        text=_finish_pages(pages),
        pages=pages,
        avg_confidence=sum(nonempty) / len(nonempty) if nonempty else 0.0,
        engine=_engine_name(route, model),
        warnings=warnings,
    )


def _with_local_when_cloud_unavailable(cloud, local, *, base_url: str) -> OcrDocumentResult:
    """If the cloud walk raises, run local RapidOCR instead of failing the book."""
    try:
        return cloud()
    except DocumentLoadCancelled:
        raise
    except Exception as exc:
        reason = _describe_cloud_failure(exc, base_url=base_url)
        logger.warning("cloud OCR unavailable, using local RapidOCR: %s", reason)
        result = local()
        result.warnings.append(f"云端 OCR 不可用（{reason}），已改用本地 RapidOCR")
        return result


def ocr_images(
    images: Iterable[tuple[int, bytes]],
    *,
    total: int,
    settings: Settings | None = None,
    on_progress: OcrProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> OcrDocumentResult:
    """OCR encoded page images without retaining the whole book in memory."""
    runtime_settings = settings or Settings()
    if ocr_cloud_configured(runtime_settings):
        return _with_local_when_cloud_unavailable(
            lambda: _ocr_images_cloud(
                images,
                total=total,
                settings=runtime_settings,
                on_progress=on_progress,
                cancel_event=cancel_event,
            ),
            lambda: _ocr_images_local(
                images,
                total=total,
                on_progress=on_progress,
                cancel_event=cancel_event,
            ),
            base_url=runtime_settings.ocr_cloud_base_url.strip(),
        )
    return _ocr_images_local(
        images,
        total=total,
        on_progress=on_progress,
        cancel_event=cancel_event,
    )


def _ocr_pdf_cloud(
    path: Path,
    *,
    settings: Settings,
    dpi: int | None = None,
    page_nums: list[int] | None = None,
    on_progress: OcrProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> OcrDocumentResult:
    _ensure_fitz()
    import fitz

    render_dpi = dpi if dpi is not None else config.OCR_PDF_DPI
    base_url = settings.ocr_cloud_base_url.strip()
    model = settings.ocr_cloud_model.strip()
    headers = {"Authorization": f"Bearer {(settings.ocr_cloud_api_key or '').strip()}"}
    doc = fitz.open(str(path))
    try:
        if page_nums:
            targets = sorted({n for n in page_nums if 1 <= n <= doc.page_count})
        else:
            targets = list(range(1, doc.page_count + 1))
        pages: list[OcrPageResult] = []
        warnings: list[str] = []
        route = _OcrRoute()
        with httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            headers=headers,
            timeout=settings.ocr_cloud_timeout_seconds,
        ) as client:
            total = len(targets)
            for progress_idx, page_num in enumerate(targets, start=1):
                try:
                    page = doc.load_page(page_num - 1)
                    pix = page.get_pixmap(dpi=render_dpi, alpha=False)
                    try:
                        image_bytes = pix.tobytes("jpeg", jpg_quality=85)
                    finally:
                        del pix
                except DocumentLoadCancelled:
                    raise
                except Exception as exc:
                    warnings.append(f"p.{page_num} 页面渲染失败，已跳过：{exc}")
                    pages.append(
                        OcrPageResult(
                            page_num=page_num,
                            text="",
                            avg_confidence=0.0,
                            low_confidence=False,
                        )
                    )
                    continue
                text, avg, from_local = _recognize_page(
                    page_num=page_num,
                    image_bytes=image_bytes,
                    client=client,
                    model=model,
                    base_url=base_url,
                    route=route,
                    warnings=warnings,
                    on_progress=on_progress,
                    progress_idx=progress_idx,
                    total=total,
                    kind_label="扫描版 PDF",
                    cancel_event=cancel_event,
                )
                low = from_local and avg < config.OCR_MIN_CONF and bool(text)
                if low:
                    warnings.append(f"p.{page_num} OCR 置信度偏低 ({avg:.2f})，建议人工核对原文")
                pages.append(
                    OcrPageResult(
                        page_num=page_num,
                        text=text,
                        avg_confidence=avg,
                        low_confidence=low,
                    )
                )
    finally:
        doc.close()

    nonempty = [page.avg_confidence for page in pages if page.text.strip()]
    return OcrDocumentResult(
        text=_finish_pages(pages),
        pages=pages,
        avg_confidence=sum(nonempty) / len(nonempty) if nonempty else 0.0,
        engine=_engine_name(route, model),
        warnings=warnings,
    )


def ocr_pdf(
    path: Path,
    *,
    dpi: int | None = None,
    page_nums: list[int] | None = None,
    on_progress: OcrProgressCallback | None = None,
    settings: Settings | None = None,
    cancel_event: threading.Event | None = None,
) -> OcrDocumentResult:
    """OCR PDF pages with configured cloud provider, otherwise local RapidOCR."""
    path = Path(path)
    if not path.is_file():
        raise RuntimeError(f"PDF not found: {path}")
    runtime_settings = settings or Settings()

    def local() -> OcrDocumentResult:
        return _ocr_pdf_local(
            path,
            dpi=dpi,
            page_nums=page_nums,
            on_progress=on_progress,
            cancel_event=cancel_event,
        )

    if ocr_cloud_configured(runtime_settings):
        return _with_local_when_cloud_unavailable(
            lambda: _ocr_pdf_cloud(
                path,
                settings=runtime_settings,
                dpi=dpi,
                page_nums=page_nums,
                on_progress=on_progress,
                cancel_event=cancel_event,
            ),
            local,
            base_url=runtime_settings.ocr_cloud_base_url.strip(),
        )
    return local()


def ocr_pdf_pages(
    path: Path,
    page_nums: list[int],
    *,
    dpi: int | None = None,
    on_progress: OcrProgressCallback | None = None,
    settings: Settings | None = None,
    cancel_event: threading.Event | None = None,
) -> OcrDocumentResult:
    """OCR a subset of pages (1-based indices)."""
    return ocr_pdf(
        path,
        dpi=dpi,
        page_nums=page_nums,
        on_progress=on_progress,
        settings=settings,
        cancel_event=cancel_event,
    )


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
