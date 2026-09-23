"""Extract embedded book covers for the library grid."""

from __future__ import annotations

import base64
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from posixpath import dirname, join, normpath
from typing import Any
from urllib.parse import unquote

from lumina_core.ingest.text import decode_text_bytes

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"}
_MIME_EXT = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/bmp": "bmp",
    "image/svg+xml": "svg",
}


def _ext_from_name(name: str, content_type: str | None = None) -> str:
    if content_type:
        mapped = _MIME_EXT.get(content_type.lower().split(";")[0].strip())
        if mapped:
            return mapped
    suffix = Path(name or "").suffix.lower()
    if suffix in _IMAGE_EXTS:
        return suffix.lstrip(".")
    return "jpg"


def _normalize_href(href: str) -> str:
    cleaned = unquote((href or "").split("#", 1)[0]).replace("\\", "/").lstrip("./")
    return cleaned.lower()


def extract_cover_image(path: Path, fmt: str) -> tuple[bytes, str] | None:
    """Return (image_bytes, extension) when a cover can be found."""
    fmt = (fmt or "").lower()
    try:
        if fmt == "epub":
            return _extract_epub_cover(path)
        if fmt == "fb2":
            return _extract_fb2_cover(path)
        if fmt == "pdf":
            return _extract_pdf_cover(path)
        if fmt in {"mobi", "azw", "azw3"}:
            return _extract_mobi_cover(path)
    except Exception:
        return None
    return None


def save_book_cover(
    source: Path,
    book_dir: Path,
    fmt: str,
) -> str | None:
    """Write cover next to the library original; return relative filename."""
    extracted = extract_cover_image(source, fmt)
    if not extracted:
        return None
    data, ext = extracted
    if not data:
        return None
    book_dir.mkdir(parents=True, exist_ok=True)
    filename = f"cover.{ext}"
    dest = book_dir / filename
    dest.write_bytes(data)
    return filename


def resolve_cover_file(book: dict[str, Any], books_dir: Path | None = None) -> Path | None:
    """Absolute path to a saved cover file, if present on disk."""
    rel = book.get("cover_path")
    if not rel:
        return None
    rel_path = Path(str(rel))
    if rel_path.is_absolute():
        return rel_path if rel_path.is_file() else None
    file_path = book.get("file_path")
    if file_path:
        candidate = Path(str(file_path)).parent / rel_path
        if candidate.is_file():
            return candidate
    if books_dir is not None and book.get("id"):
        candidate = books_dir / str(book["id"]) / rel_path
        if candidate.is_file():
            return candidate
    return None


def ensure_book_cover(
    book: dict[str, Any],
    *,
    books_dir: Path | None = None,
) -> Path | None:
    """Return saved cover path, extracting from the original when missing."""
    existing = resolve_cover_file(book, books_dir)
    if existing is not None:
        return existing
    file_path = book.get("file_path")
    fmt = str(book.get("format") or "")
    if not file_path or not fmt:
        return None
    source = Path(str(file_path))
    if not source.is_file():
        return None
    book_dir = source.parent
    rel = save_book_cover(source, book_dir, fmt)
    if not rel:
        return None
    return book_dir / rel


def _extract_epub_cover(path: Path) -> tuple[bytes, str] | None:
    try:
        import ebooklib
        from ebooklib import epub
    except ImportError:
        return None

    book = epub.read_epub(str(path))
    item = _epub_cover_item(book, ebooklib)
    if item is None:
        return None
    data = item.get_content()
    if not data:
        return None
    name = item.get_name() or "cover.jpg"
    media = getattr(item, "media_type", None) or getattr(item, "get_type", lambda: None)()
    content_type = media if isinstance(media, str) and media.startswith("image/") else None
    return bytes(data), _ext_from_name(name, content_type)


def _epub_cover_item(book, ebooklib_mod):
    # 1) Explicit cover-image / ITEM_COVER
    for item in book.get_items():
        props = {str(p).lower() for p in (getattr(item, "properties", None) or [])}
        if "cover-image" in props:
            return item
        if item.get_type() == getattr(ebooklib_mod, "ITEM_COVER", -1):
            return item

    # 2) OPF meta name="cover" → id
    for _ns, entries in (getattr(book, "metadata", None) or {}).items():
        for key, values in (entries or {}).items():
            if str(key).lower() != "cover":
                continue
            for value in values:
                cover_id = value[0] if isinstance(value, (list, tuple)) else value
                if not cover_id:
                    continue
                found = book.get_item_with_id(str(cover_id))
                if found is not None:
                    return found

    # DC / OPF get_metadata variants
    for namespace in ("OPF", "META"):
        try:
            rows = book.get_metadata(namespace, "cover") or []
        except Exception:
            rows = []
        for row in rows:
            cover_id = row[0] if isinstance(row, (list, tuple)) else row
            if not cover_id:
                continue
            found = book.get_item_with_id(str(cover_id))
            if found is not None:
                return found

    # 3) guide type=cover
    for entry in getattr(book, "guide", None) or []:
        if isinstance(entry, dict):
            epub_type = str(entry.get("type") or "").lower()
            href = str(entry.get("href") or "")
        else:
            epub_type = str(getattr(entry, "type", "") or "").lower()
            href = str(getattr(entry, "href", "") or "")
        if "cover" not in epub_type or not href:
            continue
        key = _normalize_href(href)
        found = book.get_item_with_href(href) or book.get_item_with_href(key)
        if found is None:
            for item in book.get_items():
                if _normalize_href(item.get_name() or "") == key:
                    found = item
                    break
        if found is not None:
            if found.get_type() == ebooklib_mod.ITEM_DOCUMENT:
                nested = _first_image_in_document(book, found)
                if nested is not None:
                    return nested
            return found

    # 4) First image referenced by the first spine document (homepage cover)
    from lumina_core.ingest.epub import _iter_document_items, _is_nav_item

    for doc in _iter_document_items(book, ebooklib_mod):
        if _is_nav_item(doc):
            continue
        nested = _first_image_in_document(book, doc)
        if nested is not None:
            return nested
        break
    return None


def _first_image_in_document(book, document_item):
    from lumina_core.ingest.epub import _PageImageParser, _normalize_href as epub_norm

    try:
        raw_html = document_item.get_content().decode("utf-8", errors="replace")
    except Exception:
        return None
    parser = _PageImageParser()
    try:
        parser.feed(raw_html)
        parser.close()
    except Exception:
        return None
    if not parser.sources:
        return None
    base = dirname((document_item.get_name() or "").replace("\\", "/"))
    by_href = {
        epub_norm(item.get_name() or ""): item
        for item in book.get_items()
        if item.get_name()
    }
    for source in parser.sources:
        resolved = normpath(join(base, source)).lstrip("./")
        item = book.get_item_with_href(resolved) or by_href.get(epub_norm(resolved))
        if item is not None and item.get_content():
            return item
    return None


def _extract_fb2_cover(path: Path) -> tuple[bytes, str] | None:
    try:
        root = ET.fromstring(decode_text_bytes(path.read_bytes()))
    except (ET.ParseError, OSError, LookupError):
        return None

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    cover_href = None
    for node in root.iter():
        if local(node.tag) != "coverpage":
            continue
        for child in node.iter():
            if local(child.tag) != "image":
                continue
            for key, value in child.attrib.items():
                if key.endswith("href") or key == "href":
                    cover_href = (value or "").lstrip("#")
                    break
            if cover_href:
                break
        if cover_href:
            break
    if not cover_href:
        return None

    for node in root.iter():
        if local(node.tag) != "binary":
            continue
        binary_id = node.attrib.get("id") or ""
        if binary_id != cover_href:
            continue
        content_type = node.attrib.get("content-type")
        raw = "".join((node.text or "").split())
        if not raw:
            return None
        try:
            data = base64.b64decode(raw)
        except Exception:
            return None
        return data, _ext_from_name(binary_id, content_type)
    return None


def _extract_pdf_cover(path: Path) -> tuple[bytes, str] | None:
    try:
        import fitz  # pymupdf
    except ImportError:
        return None
    try:
        doc = fitz.open(str(path))
    except Exception:
        return None
    try:
        if doc.page_count < 1:
            return None
        page = doc[0]
        # Prefer an embedded image on the first page (common scan/cover layout).
        images = page.get_images(full=True) or []
        for img in images:
            xref = img[0]
            try:
                extracted = doc.extract_image(xref)
            except Exception:
                continue
            data = extracted.get("image")
            if not data:
                continue
            ext = str(extracted.get("ext") or "jpg").lower()
            if ext == "jpeg":
                ext = "jpg"
            return bytes(data), ext
        # Fallback: rasterize the first page at modest DPI.
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        return pix.tobytes("jpeg"), "jpg"
    finally:
        doc.close()


def _extract_mobi_cover(path: Path) -> tuple[bytes, str] | None:
    try:
        import mobi
    except ImportError:
        return None
    import shutil
    import tempfile

    tempdir = None
    try:
        tempdir, extracted = mobi.extract(str(path))
        extracted_path = Path(extracted)
        if extracted_path.suffix.lower() == ".epub":
            return _extract_epub_cover(extracted_path)
        # Some extractions trees expose HTML + images; pick a cover-named image.
        for candidate in extracted_path.rglob("*"):
            if not candidate.is_file():
                continue
            name = candidate.name.lower()
            if candidate.suffix.lower() not in _IMAGE_EXTS:
                continue
            if "cover" in name:
                return candidate.read_bytes(), _ext_from_name(candidate.name)
    except Exception:
        return None
    finally:
        if tempdir:
            shutil.rmtree(tempdir, ignore_errors=True)
    return None


_COVER_BYTES_KEYS = re.compile(r"^cover_(bytes|data|bin)$", re.IGNORECASE)


def strip_cover_payload(metadata: dict[str, Any]) -> dict[str, Any]:
    """Ensure binary cover payloads never land in metadata_json."""
    return {k: v for k, v in metadata.items() if not _COVER_BYTES_KEYS.match(str(k))}
