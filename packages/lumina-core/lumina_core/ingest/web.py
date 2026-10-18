"""Download a public HTML page and keep its readable text.

Direct fetch only. Login, scripts, and third-party reader proxies are out of scope.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx

MAX_HTML_BYTES = 15 * 1024 * 1024
FETCH_TIMEOUT_S = 45.0
FETCH_ATTEMPTS = 3

_HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_USER_AGENT = "Mozilla/5.0 (compatible; Lumina/1.0)"


class WebImportError(Exception):
    """User-facing failure for a URL that cannot become a book."""


@dataclass(frozen=True)
class WebPage:
    final_url: str
    title: str
    text: str


def canonicalize_import_url(raw: str) -> str:
    """Normalize a user-typed URL for dedup. Rejects anything that is not http(s)."""
    text = (raw or "").strip()
    if not text or any(ch.isspace() for ch in text):
        raise WebImportError("不是有效的网址")
    parsed = urlsplit(text)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        raise WebImportError("仅支持 http 或 https 网址")
    host = parsed.hostname.lower()
    port = parsed.port
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None
    netloc = f"{host}:{port}" if port else host
    path = parsed.path or ""
    if path == "/" or (len(path) > 1 and path.endswith("/")):
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, parsed.query, ""))


def url_import_hash(canonical: str) -> str:
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _charset(content_type: str) -> str:
    for part in content_type.split(";")[1:]:
        item = part.strip()
        if item.lower().startswith("charset="):
            name = item.split("=", 1)[1].strip().strip('"').strip("'")
            return name or "utf-8"
    return "utf-8"


def _media_type(content_type: str) -> str:
    return content_type.split(";", 1)[0].strip().lower()


def _download_html(canonical: str, *, timeout: float) -> tuple[str, str, str]:
    """Return (html, final_url, media_type). Raises WebImportError or transport errors."""
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    }
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        with client.stream("GET", canonical, headers=headers) as resp:
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            media = _media_type(content_type)
            if media and media not in _HTML_TYPES:
                raise WebImportError("不是可下载的网页")
            payload = bytearray()
            for chunk in resp.iter_bytes():
                if not chunk:
                    continue
                payload.extend(chunk)
                if len(payload) > MAX_HTML_BYTES:
                    raise WebImportError("网页超过 15MB，无法导入")
            final_url = str(resp.url)
    html = bytes(payload).decode(_charset(content_type), errors="replace")
    return html, final_url, media


def fetch_web_page(url: str, *, timeout: float = FETCH_TIMEOUT_S) -> WebPage:
    """GET one public page and extract readable Markdown. Raises WebImportError."""
    canonical = canonicalize_import_url(url)
    last_exc: Exception | None = None
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        try:
            html, final_url, media = _download_html(canonical, timeout=timeout)
            break
        except WebImportError:
            raise
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code if exc.response is not None else 0
            raise WebImportError(f"下载失败：HTTP {code}") from exc
        except (httpx.TransportError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt >= FETCH_ATTEMPTS:
                raise WebImportError(f"下载失败：{exc}") from exc
            time.sleep(0.4 * attempt)
    else:
        raise WebImportError(f"下载失败：{last_exc}") from last_exc

    if not media and "<html" not in html[:500].lower() and "<!doctype html" not in html[:500].lower():
        raise WebImportError("不是可下载的网页")
    title, text = _extract_markdown(html, url=final_url or canonical)
    if not text.strip():
        raise WebImportError("未能抽取正文")
    return WebPage(final_url=final_url or canonical, title=title.strip(), text=text.strip())


# Used when PyInstaller omits trafilatura/settings.cfg. ConfigParser lowercases
# option names, so the missing-file error reads min_extracted_size.
_TRAFILATURA_FALLBACK = {
    "MIN_EXTRACTED_SIZE": "250",
    "MIN_EXTRACTED_COMM_SIZE": "1",
    "MIN_OUTPUT_SIZE": "1",
    "MIN_OUTPUT_COMM_SIZE": "1",
    "MIN_DUPLCHECK_SIZE": "100",
    "MAX_REPETITIONS": "2",
    "MAX_FILE_SIZE": "20000000",
    "MIN_FILE_SIZE": "10",
    "DOWNLOAD_TIMEOUT": "30",
    "SLEEP_TIME": "5",
    "MAX_REDIRECTS": "2",
    "EXTRACTION_TIMEOUT": "30",
    "EXTENSIVE_DATE_SEARCH": "off",
    "EXTERNAL_URLS": "off",
    "USER_AGENTS": "",
    "COOKIE": "",
    "MAX_TREE_SIZE": "",
}


def ensure_trafilatura_config() -> None:
    """Fill trafilatura defaults when the packaged settings.cfg did not load."""
    from trafilatura.settings import DEFAULT_CONFIG

    for key, value in _TRAFILATURA_FALLBACK.items():
        if not DEFAULT_CONFIG.has_option("DEFAULT", key):
            DEFAULT_CONFIG["DEFAULT"][key] = value


def _extract_markdown(html: str, *, url: str) -> tuple[str, str]:
    import trafilatura

    ensure_trafilatura_config()
    extracted = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=True,
        favor_recall=True,
        output_format="markdown",
        url=url,
    )
    title = ""
    meta = trafilatura.extract_metadata(html)
    if meta and meta.title:
        title = str(meta.title).strip()
    return title, (extracted or "").strip()


def write_web_markdown(dest: Path, text: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
