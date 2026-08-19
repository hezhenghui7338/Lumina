"""EPUB parsing via ebooklib — spine → chapters → plain text."""

from __future__ import annotations

import re
from html import unescape
from pathlib import Path


def _html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = re.sub(r"(?i)</h[1-6]>", "\n\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _chapter_title(item, raw_html: str, href: str) -> str:
    title = getattr(item, "title", None)
    if isinstance(title, str) and title.strip():
        return title.strip()
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw_html)
    if match:
        extracted = _html_to_text(match.group(1))
        if extracted:
            return extracted
    name = item.get_name() or href
    return Path(name).stem.replace("_", " ")


def _spine_idref(spine_entry) -> str:
    if isinstance(spine_entry, tuple):
        return str(spine_entry[0])
    return str(spine_entry)


def _item_from_spine(book, spine_entry):
    """ebooklib spine stores item IDs (idref), not hrefs."""
    idref = _spine_idref(spine_entry)
    item = book.get_item_with_id(idref)
    if item is not None:
        return item
    return book.get_item_with_href(idref)


def _is_nav_item(item) -> bool:
    name = (item.get_name() or "").lower()
    item_id = (getattr(item, "id", None) or "").lower()
    if item_id == "nav" or name.endswith("nav.xhtml") or name.endswith("toc.xhtml"):
        return True
    props = getattr(item, "properties", None) or []
    return "nav" in props


def _iter_document_items(book, ebooklib_mod):
    seen: set[str] = set()
    for spine_entry in book.spine:
        item = _item_from_spine(book, spine_entry)
        if item is None or item.get_type() != ebooklib_mod.ITEM_DOCUMENT:
            continue
        key = item.get_id() or item.get_name()
        if not key or key in seen:
            continue
        seen.add(key)
        yield item

    if seen:
        return

    for item in book.get_items_of_type(ebooklib_mod.ITEM_DOCUMENT):
        key = item.get_id() or item.get_name()
        if not key or key in seen:
            continue
        seen.add(key)
        yield item


def load_epub(path: Path) -> tuple[str, dict]:
    try:
        import ebooklib
        from ebooklib import epub
    except ImportError as e:
        raise RuntimeError("EPUB support requires ebooklib: pip install ebooklib") from e

    book = epub.read_epub(str(path))
    title = (book.get_metadata("DC", "title") or [[None]])[0][0]
    author = (book.get_metadata("DC", "creator") or [[None]])[0][0]

    parts: list[str] = []
    skipped_chapters = 0

    for item in _iter_document_items(book, ebooklib):
        if _is_nav_item(item):
            skipped_chapters += 1
            continue

        href = item.get_name() or item.get_id() or ""
        try:
            raw_html = item.get_content().decode("utf-8", errors="replace")
        except Exception:
            skipped_chapters += 1
            continue

        body = _html_to_text(raw_html)
        if not body:
            skipped_chapters += 1
            continue
        chapter_title = _chapter_title(item, raw_html, href)
        parts.append(f"## [§{chapter_title}]\n{body}")

    metadata: dict = {"title": title, "author": author}
    if skipped_chapters:
        metadata["skipped_chapters"] = skipped_chapters

    return "\n\n".join(parts), metadata
