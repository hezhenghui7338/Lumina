"""EPUB parsing via ebooklib — spine → chapters → plain text."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

from lumina_core.chunker.roles import DocumentRole, classify_heading, landmark_role
from lumina_core.ingest.html import parse_html_document


def _html_to_text(html: str) -> str:
    try:
        text, _metadata = parse_html_document(html)
        return text
    except ValueError:
        return ""


def _chapter_title(
    item,
    raw_html: str,
    href: str,
    *,
    fallback_title: str = "",
    html_title: str = "",
) -> str:
    title = getattr(item, "title", None)
    if isinstance(title, str) and title.strip():
        return title.strip()
    if fallback_title.strip():
        return fallback_title.strip()
    if html_title.strip():
        return html_title.strip()
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw_html)
    if match:
        extracted = _html_to_text(match.group(1))
        if extracted:
            return extracted
    heading = re.search(r"(?is)<h[1-6][^>]*>(.*?)</h[1-6]>", raw_html)
    if heading:
        extracted = _html_to_text(heading.group(1))
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


def _normalize_href(href: str) -> str:
    cleaned = unquote((href or "").split("#", 1)[0]).replace("\\", "/").lstrip("./")
    return cleaned.lower()


_LANDMARK_HREF = re.compile(
    r"<a\b([^>]*)>",
    re.IGNORECASE,
)
_ATTR = re.compile(r"""(?:epub:type|type|href)\s*=\s*["']([^"']+)["']""", re.IGNORECASE)


def _epub_landmark_roles(book) -> dict[str, tuple[DocumentRole, str]]:
    """Map spine hrefs to (role, title) from OPF guide / EPUB3 landmarks."""
    lookup: dict[str, tuple[DocumentRole, str]] = {}
    for entry in getattr(book, "guide", None) or []:
        if not isinstance(entry, dict):
            href = str(getattr(entry, "href", "") or "")
            epub_type = str(getattr(entry, "type", "") or "")
            title = str(getattr(entry, "title", "") or "").strip()
            if not href:
                continue
            mapped = landmark_role(epub_type) or classify_heading(title or href)
            lookup[_normalize_href(href)] = (mapped, title)
            continue
        href = _normalize_href(str(entry.get("href") or ""))
        title = str(entry.get("title") or "").strip()
        mapped = landmark_role(str(entry.get("type") or ""))
        if href and mapped is not None:
            lookup[href] = (mapped, title)
        elif href:
            lookup[href] = (classify_heading(title or href), title)

    get_items = getattr(book, "get_items", None)
    items = list(get_items()) if callable(get_items) else []
    for item in items:
        name = (item.get_name() or "").lower()
        props = getattr(item, "properties", None) or []
        if "nav" not in props and "nav" not in name and not name.endswith("nav.xhtml"):
            continue
        try:
            html = item.get_content().decode("utf-8", errors="replace")
        except Exception:
            continue
        if "landmarks" not in html.lower() and "epub:type" not in html.lower():
            continue
        for tag in _LANDMARK_HREF.finditer(html):
            attrs = tag.group(1)
            epub_type = ""
            href = ""
            for attr in _ATTR.finditer(attrs):
                raw = attr.group(0).lower()
                value = attr.group(1)
                if raw.startswith("href"):
                    href = value
                else:
                    epub_type = value.split()[-1]
            mapped = landmark_role(epub_type)
            key = _normalize_href(href)
            if key and mapped is not None:
                lookup[key] = (mapped, lookup.get(key, (mapped, ""))[1])
    return lookup


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
    landmark_lookup = _epub_landmark_roles(book)
    structure_roles: list[dict] = []

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
        html_title = ""
        try:
            _body, html_meta = parse_html_document(raw_html)
            html_title = str(html_meta.get("title") or "")
        except ValueError:
            pass
        landmark = landmark_lookup.get(_normalize_href(href))
        chapter_title = _chapter_title(
            item,
            raw_html,
            href,
            fallback_title=(landmark[1] if landmark else ""),
            html_title=html_title,
        )
        marker = f"## [§{chapter_title}]"
        if body.lstrip().startswith(marker):
            parts.append(body)
        else:
            parts.append(f"{marker}\n{body}")
        role = (landmark[0] if landmark else None) or classify_heading(chapter_title)
        structure_roles.append({"title": chapter_title, "role": role.value})

    metadata: dict = {"title": title, "author": author}
    if skipped_chapters:
        metadata["skipped_chapters"] = skipped_chapters
    if structure_roles:
        metadata["structure_roles"] = structure_roles

    return "\n\n".join(parts), metadata
