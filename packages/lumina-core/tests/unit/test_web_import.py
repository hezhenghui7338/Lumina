"""Public HTML fetch for library URL import."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from lumina_core.ingest.web import (
    WebImportError,
    canonicalize_import_url,
    fetch_web_page,
    url_import_hash,
)


_ARTICLE = """<!DOCTYPE html>
<html><head><title>示例文章</title></head>
<body><article><h1>示例文章</h1>
<p>这是一段足够长的正文，用来确认网页导入能抽出可读文本，而不是只留下导航。</p>
</article></body></html>
""".encode()


class _Resp:
    def __init__(self, body: bytes, content_type: str, *, status: int = 200, url: str = "https://example.com/post"):
        self._body = body
        self.headers = {"content-type": content_type}
        self.status_code = status
        self.url = httpx.URL(url)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", str(self.url))
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)

    def iter_bytes(self):
        yield self._body


class _Stream:
    def __init__(self, resp: _Resp):
        self.resp = resp

    def __enter__(self) -> _Resp:
        return self.resp

    def __exit__(self, *args: object) -> bool:
        return False


class _Client:
    def __init__(self, resp: _Resp):
        self.resp = resp

    def __enter__(self) -> _Client:
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def stream(self, method: str, url: str, headers: dict | None = None) -> _Stream:
        return _Stream(self.resp)


def test_canonicalize_strips_fragment_slash_and_host_case():
    left = canonicalize_import_url("HTTPS://Example.COM/a/#section")
    right = canonicalize_import_url("https://example.com/a")
    assert left == right == "https://example.com/a"
    assert url_import_hash(left) == url_import_hash(right)


def test_canonicalize_rejects_non_http():
    with pytest.raises(WebImportError):
        canonicalize_import_url("ftp://example.com/a")
    with pytest.raises(WebImportError):
        canonicalize_import_url("notaurl")


def test_fetch_html_extracts_title_and_text(monkeypatch):
    monkeypatch.setattr(
        "lumina_core.ingest.web.httpx.Client",
        lambda *args, **kwargs: _Client(_Resp(_ARTICLE, "text/html; charset=utf-8")),
    )
    page = fetch_web_page("https://example.com/post")
    assert page.title == "示例文章"
    assert "可读文本" in page.text


def test_fetch_rejects_non_html(monkeypatch):
    monkeypatch.setattr(
        "lumina_core.ingest.web.httpx.Client",
        lambda *args, **kwargs: _Client(_Resp(b"%PDF-1.4", "application/pdf")),
    )
    with pytest.raises(WebImportError, match="不是可下载的网页"):
        fetch_web_page("https://example.com/file.pdf")


def test_extract_works_when_trafilatura_settings_file_is_missing():
    """Release sidecar omits settings.cfg; ConfigParser then lacks min_extracted_size."""
    from configparser import ConfigParser

    import trafilatura.settings as settings

    from lumina_core.ingest.web import _extract_markdown

    saved = settings.DEFAULT_CONFIG
    settings.DEFAULT_CONFIG = ConfigParser()
    try:
        title, text = _extract_markdown(_ARTICLE.decode(), url="https://example.com/post")
    finally:
        settings.DEFAULT_CONFIG = saved
    assert title == "示例文章"
    assert "可读文本" in text


def test_pyinstaller_spec_bundles_trafilatura_settings():
    spec = Path(__file__).resolve().parents[2] / "lumina-core.spec"
    text = spec.read_text(encoding="utf-8")
    assert '"trafilatura"' in text
    assert '"justext"' in text


def test_fetch_retries_transient_tls_eof(monkeypatch):
    sleeps: list[float] = []
    calls = {"n": 0}
    monkeypatch.setattr("lumina_core.ingest.web.time.sleep", sleeps.append)

    class _Flaky:
        def __init__(self, *args, **kwargs):
            return None

        def __enter__(self) -> _Flaky:
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def stream(self, method: str, url: str, headers: dict | None = None) -> _Stream:
            calls["n"] += 1
            if calls["n"] < 3:
                raise httpx.ReadError("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol")
            return _Stream(_Resp(_ARTICLE, "text/html; charset=utf-8"))

    monkeypatch.setattr("lumina_core.ingest.web.httpx.Client", _Flaky)
    page = fetch_web_page("https://example.com/post")
    assert "可读文本" in page.text
    assert sleeps == [0.4, 0.8]


def test_fetch_rejects_empty_article(monkeypatch):
    html = "<html><head><title>空</title></head><body></body></html>".encode()
    monkeypatch.setattr(
        "lumina_core.ingest.web.httpx.Client",
        lambda *args, **kwargs: _Client(_Resp(html, "text/html")),
    )
    with pytest.raises(WebImportError, match="未能抽取正文"):
        fetch_web_page("https://example.com/empty")
