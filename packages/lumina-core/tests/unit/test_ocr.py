"""OCR unit tests (mocked RapidOCR; optional deps not required)."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

from lumina_core import config
from lumina_core.config import Settings
from lumina_core.ingest.ocr import (
    OcrDocumentResult,
    OcrPageResult,
    _cloud_request,
    _ocr_images_cloud,
    ocr_available,
    ocr_cloud_configured,
    ocr_dependency_warning,
    ocr_install_hint,
    ocr_images,
    ocr_metadata_from_result,
    ocr_pdf,
)
from lumina_core.ingest.progress import DocumentLoadCancelled
from lumina_core.ingest.pdf import load_pdf
from lumina_core.main import smoke_ocr
from tests.support.ocr_helpers import (
    fake_ocr_document,
    fake_ocr_pdf,
    live_ocr_skip_reason,
    write_blank_pdf,
    write_image_only_pdf,
)

_LIVE_OCR_SKIP = live_ocr_skip_reason()


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


@pytest.mark.skipif(_LIVE_OCR_SKIP is not None, reason=_LIVE_OCR_SKIP or "")
def test_ocr_pdf_on_image_only_page(tmp_path: Path):
    """Live OCR stack: image-only PDF should yield non-empty text."""
    pdf = tmp_path / "image-only.pdf"
    write_image_only_pdf(pdf, text="SCAN123")
    result = ocr_pdf(pdf)
    assert result.text.strip()
    assert result.pages
    normalized = result.text.upper()
    assert "SCAN" in normalized or "123" in normalized


@pytest.mark.skipif(_LIVE_OCR_SKIP is not None, reason=_LIVE_OCR_SKIP or "")
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


def test_cloud_ocr_configuration_requires_all_fields():
    assert not ocr_cloud_configured(Settings(ocr_cloud_base_url="https://example.test/v1"))
    assert ocr_cloud_configured(
        Settings(
            ocr_cloud_base_url="https://example.test/v1",
            ocr_cloud_model="vision-model",
            ocr_cloud_api_key="secret",
        )
    )


def test_ocr_pdf_prefers_cloud_without_initializing_local(tmp_path: Path, monkeypatch):
    pdf = tmp_path / "scan.pdf"
    write_blank_pdf(pdf)
    expected = OcrDocumentResult(text="云端文字", engine="openai-compatible/vision")
    monkeypatch.setattr("lumina_core.ingest.ocr._ocr_pdf_cloud", lambda *_args, **_kwargs: expected)
    monkeypatch.setattr(
        "lumina_core.ingest.ocr._ocr_pdf_local",
        lambda *_args, **_kwargs: pytest.fail("云端配置完整时不应初始化本地 OCR"),
    )
    settings = Settings(
        ocr_cloud_base_url="https://example.test/v1",
        ocr_cloud_model="vision",
        ocr_cloud_api_key="secret",
    )
    assert ocr_pdf(pdf, settings=settings) is expected


def test_ocr_pdf_cloud_unavailable_uses_local(tmp_path: Path, monkeypatch):
    """A cloud walker that raises must not fail the book; local RapidOCR takes over."""
    pdf = tmp_path / "scan.pdf"
    write_blank_pdf(pdf)
    local = OcrDocumentResult(
        text="## [p.1]\n本地正文",
        pages=[OcrPageResult(1, "本地正文", 0.9, False)],
        engine="rapidocr/pp-ocrv6",
    )

    def fail_cloud(*_args, **_kwargs):
        raise RuntimeError("云端 OCR 请求超时")

    monkeypatch.setattr("lumina_core.ingest.ocr._ocr_pdf_cloud", fail_cloud)
    monkeypatch.setattr("lumina_core.ingest.ocr._ocr_pdf_local", lambda *_args, **_kwargs: local)
    result = ocr_pdf(pdf, settings=_cloud_settings())
    assert result is local
    assert "本地正文" in result.text
    assert any("已改用本地 RapidOCR" in item for item in result.warnings)


def test_load_pdf_cloud_unavailable_keeps_local_text(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "OCR_ENABLED", True)
    pdf = tmp_path / "scan.pdf"
    write_blank_pdf(pdf, pages=1)
    local = OcrDocumentResult(
        text="## [p.1]\n本地承接",
        pages=[OcrPageResult(1, "本地承接", 0.9, False)],
        engine="rapidocr/pp-ocrv6",
    )

    def fail_cloud(*_args, **_kwargs):
        raise RuntimeError("云端 OCR 请求超时")

    monkeypatch.setattr("lumina_core.ingest.ocr._ocr_pdf_cloud", fail_cloud)
    monkeypatch.setattr("lumina_core.ingest.ocr._ocr_pdf_local", lambda *_args, **_kwargs: local)
    text, meta = load_pdf(pdf, settings=_cloud_settings())
    assert "本地承接" in text
    assert meta.get("ocr") is True
    assert meta.get("ocr_used") is True


def test_ocr_pdf_cancel_does_not_fall_back_to_local(tmp_path: Path, monkeypatch):
    pdf = tmp_path / "scan.pdf"
    write_blank_pdf(pdf)

    def cancel(*_args, **_kwargs):
        raise DocumentLoadCancelled("已取消")

    monkeypatch.setattr("lumina_core.ingest.ocr._ocr_pdf_cloud", cancel)
    monkeypatch.setattr(
        "lumina_core.ingest.ocr._ocr_pdf_local",
        lambda *_args, **_kwargs: pytest.fail("取消时不应改走本地"),
    )
    with pytest.raises(DocumentLoadCancelled):
        ocr_pdf(pdf, settings=_cloud_settings())


def test_ocr_images_cloud_unavailable_uses_local(monkeypatch):
    local = OcrDocumentResult(text="本地图", engine="rapidocr/pp-ocrv6", pages=[])

    def fail_cloud(*_args, **_kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("lumina_core.ingest.ocr._ocr_images_cloud", fail_cloud)
    monkeypatch.setattr("lumina_core.ingest.ocr._ocr_images_local", lambda *_args, **_kwargs: local)
    result = ocr_images([(1, b"img")], total=1, settings=_cloud_settings())
    assert "本地图" in result.text
    assert any("已改用本地 RapidOCR" in item for item in result.warnings)


def _cloud_settings() -> Settings:
    return Settings(
        ocr_cloud_base_url="https://example.test/v1",
        ocr_cloud_model="vision",
        ocr_cloud_api_key="secret",
        ocr_cloud_timeout_seconds=5,
    )


def _run_cloud_images(handler, images, monkeypatch, local):
    monkeypatch.setattr("lumina_core.ingest.ocr._ocr_encoded_image_local", local)
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("lumina_core.ingest.ocr.httpx.Client", client_factory)
    return _ocr_images_cloud(
        images,
        total=len(images),
        settings=_cloud_settings(),
        on_progress=None,
        cancel_event=None,
    )


def test_cloud_page_timeout_retries_then_local_for_rest(monkeypatch):
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": "云端页"}}]})
        raise httpx.ReadTimeout("The read operation timed out")

    local_pages: list[int] = []

    def local(image_bytes: bytes):
        local_pages.append(len(image_bytes))
        return "本地页", 0.91

    result = _run_cloud_images(
        handler,
        [(1, b"page-one"), (2, b"page-two"), (3, b"page-three")],
        monkeypatch,
        local,
    )
    assert calls["n"] == 5  # page 1 once, page 2 four times; page 3 stays local
    assert local_pages == [len(b"page-two"), len(b"page-three")]
    assert "云端页" in result.text
    assert result.text.count("本地页") == 2
    assert "rapidocr/pp-ocrv6" in result.engine
    assert "openai-compatible/vision" in result.engine
    assert any("已重试 3 次" in item and "ReadTimeout" in item for item in result.warnings)
    assert any("自该页起改用本地" in item for item in result.warnings)


def test_local_page_failure_skips_and_continues(monkeypatch):
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("The read operation timed out")

    seen = {"n": 0}

    def local(_image_bytes: bytes):
        seen["n"] += 1
        if seen["n"] == 1:
            raise RuntimeError("rapidocr boom")
        return "第二页", 0.8

    result = _run_cloud_images(handler, [(1, b"a"), (2, b"bb")], monkeypatch, local)
    assert result.pages[0].text == "（本页识别出错）"
    assert "第二页" in result.pages[1].text
    assert any("p.1 本地 OCR 失败，已跳过" in item for item in result.warnings)
    assert seen["n"] == 2


def test_every_page_failure_keeps_error_notes(monkeypatch):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    def local(_image_bytes: bytes):
        raise RuntimeError("rapidocr boom")

    result = _run_cloud_images(handler, [(1, b"a"), (2, b"b")], monkeypatch, local)
    assert result.pages[0].text == "（本页识别出错）"
    assert result.pages[1].text == "（本页识别出错）"
    assert "（本页识别出错）" in result.text
    assert any("已跳过" in item for item in result.warnings)


def test_load_pdf_keeps_book_when_ocr_pages_are_blank(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "OCR_ENABLED", True)

    def blank_ocr(_path, **_kwargs):
        return OcrDocumentResult(
            text="",
            pages=[
                OcrPageResult(page_num=1, text="第一页原文", avg_confidence=0.9, low_confidence=False),
                OcrPageResult(page_num=2, text="", avg_confidence=0.0, low_confidence=False),
            ],
        )

    monkeypatch.setattr("lumina_core.ingest.pdf.ocr_pdf", blank_ocr)
    pdf = tmp_path / "scan.pdf"
    write_blank_pdf(pdf, pages=2)
    text, meta = load_pdf(pdf)
    assert meta.get("ocr_used") is True
    assert "第一页原文" in text
    assert "（本页识别出错）" in text
    assert "## [p.2]" in text


def test_cancel_during_cloud_ocr_does_not_retry(monkeypatch):
    calls = {"n": 0}

    def boom(*_args, **_kwargs):
        calls["n"] += 1
        raise DocumentLoadCancelled("已取消")

    monkeypatch.setattr("lumina_core.ingest.ocr._cloud_request", boom)
    monkeypatch.setattr(
        "lumina_core.ingest.ocr._ocr_encoded_image_local",
        lambda *_args, **_kwargs: pytest.fail("取消时不应改走本地"),
    )
    with pytest.raises(DocumentLoadCancelled):
        _ocr_images_cloud(
            [(1, b"a"), (2, b"b")],
            total=2,
            settings=_cloud_settings(),
            on_progress=None,
            cancel_event=None,
        )
    assert calls["n"] == 1


def test_cloud_request_sends_image_and_parses_text():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = __import__("json").loads(request.content)
        assert payload["model"] == "vision-model"
        image_url = payload["messages"][0]["content"][1]["image_url"]["url"]
        assert image_url.startswith("data:image/jpeg;base64,")
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "识别结果"}}]},
        )

    with httpx.Client(
        base_url="https://example.test/v1/",
        transport=httpx.MockTransport(handler),
    ) as client:
        text = _cloud_request(client, model="vision-model", image_bytes=b"jpeg")
    assert text == "识别结果"


def test_cloud_request_unauthorized_is_readable():
    transport = httpx.MockTransport(lambda _request: httpx.Response(401))
    with (
        httpx.Client(base_url="https://example.test/v1/", transport=transport) as client,
        pytest.raises(RuntimeError, match="API Key 无效"),
    ):
        _cloud_request(client, model="vision-model", image_bytes=b"jpeg")
