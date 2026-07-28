"""MOBI extraction via mobi library."""

from __future__ import annotations

import re
import shutil
import tempfile
from html import unescape
from pathlib import Path


def _html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def load_mobi(path: Path) -> tuple[str, dict]:
    try:
        import mobi
    except ImportError as e:
        raise RuntimeError("MOBI support requires mobi: pip install mobi") from e

    tempdir: str | None = None
    try:
        tempdir, extracted = mobi.extract(str(path))
        extracted_path = Path(extracted)
        if not extracted_path.exists():
            raise ValueError(f"mobi.extract produced no file: {extracted}")

        suffix = extracted_path.suffix.lower()
        if suffix in {".html", ".htm", ".xhtml"}:
            html = extracted_path.read_text(encoding="utf-8", errors="replace")
            return _html_to_text(html), {"mobi_extract_type": "html"}
        if suffix == ".epub":
            from lumina_core.ingest.epub import load_epub

            return load_epub(extracted_path)
        if suffix == ".pdf":
            from lumina_core.ingest.pdf import load_pdf

            text, meta = load_pdf(extracted_path)
            meta["mobi_extract_type"] = "pdf"
            return text, meta
        raise ValueError(f"Unsupported MOBI extract format: {suffix}")
    except Exception as exc:
        msg = str(exc).lower()
        if "drm" in msg or "encrypt" in msg:
            raise ValueError("DRM-protected MOBI is not supported") from exc
        raise
    finally:
        if tempdir:
            shutil.rmtree(tempdir, ignore_errors=True)
