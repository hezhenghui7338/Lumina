"""EPUB parsing via ebooklib — spine → chapters → plain text."""

from __future__ import annotations

import re
import threading
from html.parser import HTMLParser
from pathlib import Path
from posixpath import dirname, join, normpath
from urllib.parse import unquote
from xml.etree import ElementTree

from lumina_core.chunker.markers import clean_structure_title, heading_marker
from lumina_core.chunker.roles import DocumentRole, classify_heading, landmark_role
from lumina_core.config import Settings
from lumina_core.ingest.html import (
    parse_html_document,
    parse_html_document_with_images,
)
from lumina_core.ingest.ocr import (
    OcrProgressCallback,
    ocr_images,
    ocr_metadata_from_result,
    ocr_result_text,
)


class _NavTocParser(HTMLParser):
    """Collect nested nav/toc links as (href, title, depth, ancestors)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[tuple[str, str, int, tuple[str, ...]]] = []
        self._list_depth = 0
        self._in_a = False
        self._href = ""
        self._text: list[str] = []
        self._li_titles: list[str | None] = []
        self._skip_nav = False
        self._nav_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr = {key.lower(): (value or "") for key, value in attrs}
        if tag == "nav":
            epub_type = (attr.get("epub:type") or attr.get("type") or "").lower()
            self._nav_depth += 1
            if "landmark" in epub_type:
                self._skip_nav = True
            elif "toc" in epub_type or not epub_type:
                self._skip_nav = False
        if self._skip_nav:
            return
        if tag in {"ol", "ul"}:
            self._list_depth += 1
        elif tag == "li":
            self._li_titles.append(None)
        elif tag == "a":
            self._in_a = True
            self._href = attr.get("href") or ""
            self._text = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "nav":
            self._nav_depth = max(0, self._nav_depth - 1)
            if self._nav_depth == 0:
                self._skip_nav = False
            return
        if self._skip_nav:
            return
        if tag == "a" and self._in_a:
            title = " ".join("".join(self._text).split())
            href = unquote(self._href.split("#", 1)[0])
            ancestors = tuple(item for item in self._li_titles[:-1] if item)
            if href and title:
                self.entries.append(
                    (href, title, max(1, self._list_depth), ancestors)
                )
                if self._li_titles:
                    self._li_titles[-1] = title
            self._in_a = False
        elif tag == "li" and self._li_titles:
            self._li_titles.pop()
        elif tag in {"ol", "ul"}:
            self._list_depth = max(0, self._list_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._in_a and not self._skip_nav:
            self._text.append(data)


class _PageImageParser(HTMLParser):
    """Collect image references in DOM order from one spine document."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() not in {"img", "image"}:
            return
        attr = {key.lower(): (value or "") for key, value in attrs}
        source = attr.get("src") or attr.get("href") or attr.get("xlink:href") or ""
        if source and not source.startswith(("data:", "http://", "https://")):
            self.sources.append(unquote(source.split("#", 1)[0]))


def _epub_nested_toc(book) -> dict[str, tuple[str, int, tuple[str, ...]]]:
    """Map normalized href -> (title, depth, ancestors) from nav or NCX."""
    lookup: dict[str, tuple[str, int, tuple[str, ...]]] = {}
    for href, title, depth, ancestors in _epub_toc_entries(book):
        key = _normalize_href(href)
        if key and key not in lookup:
            lookup[key] = (title, depth, ancestors)
    return lookup


def _epub_toc_entries(book) -> list[tuple[str, str, int, tuple[str, ...]]]:
    """Ordered TOC rows: (href, title, depth, ancestors) from nav or NCX."""
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
        parser = _NavTocParser()
        try:
            parser.feed(html)
            parser.close()
        except Exception:
            continue
        if parser.entries:
            return list(parser.entries)

    return _parse_ncx_toc(book)


def list_epub_toc_paths(epub_path: Path | str) -> list[tuple[str, ...]]:
    """Ordered full TOC paths (ancestors + leaf title) for outline repair.

    When nav/NCX is flat (no ancestors), infer 章/节 nesting from numbered titles.
    """
    from ebooklib import epub as ebooklib_epub

    from lumina_core.chunker.tree import nest_flat_outline_paths

    path = Path(epub_path)
    book = ebooklib_epub.read_epub(str(path))
    paths: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()
    for _href, title, _depth, ancestors in _epub_toc_entries(book):
        leaf = clean_structure_title(title) if title else ""
        if not leaf:
            continue
        chain = tuple(
            cleaned
            for item in (*ancestors, leaf)
            if (cleaned := clean_structure_title(item))
        )
        if not chain or chain in seen:
            continue
        seen.add(chain)
        paths.append(chain)
    return nest_flat_outline_paths(paths)


def list_mobi_toc_paths(mobi_path: Path | str) -> list[tuple[str, ...]]:
    """TOC paths from Kindle/MOBI/AZW3 via temporary EPUB extract (no DRM)."""
    import shutil
    import tempfile

    try:
        import mobi
    except ImportError as exc:
        raise RuntimeError("MOBI TOC requires mobi: pip install mobi") from exc

    path = Path(mobi_path)
    tempdir: str | None = None
    try:
        tempdir, extracted = mobi.extract(str(path))
        extracted_path = Path(extracted)
        if extracted_path.suffix.lower() != ".epub":
            return []
        return list_epub_toc_paths(extracted_path)
    finally:
        if tempdir:
            shutil.rmtree(tempdir, ignore_errors=True)


def list_book_toc_paths(
    source: Path | str,
    *,
    format_name: str | None = None,
) -> list[tuple[str, ...]]:
    """TOC paths for outline rebuild across EPUB and Kindle formats."""
    path = Path(source)
    if not path.is_file():
        return []
    fmt = (format_name or path.suffix.lstrip(".")).lower()
    if fmt == "epub" or path.suffix.lower() == ".epub":
        return list_epub_toc_paths(path)
    if fmt in {"mobi", "azw", "azw3", "kf8", "prc"} or path.suffix.lower() in {
        ".mobi",
        ".azw",
        ".azw3",
        ".prc",
    }:
        try:
            return list_mobi_toc_paths(path)
        except Exception:
            return []
    return []


def _parse_ncx_toc(book) -> list[tuple[str, str, int, tuple[str, ...]]]:
    entries: list[tuple[str, str, int, tuple[str, ...]]] = []
    get_items = getattr(book, "get_items", None)
    items = list(get_items()) if callable(get_items) else []
    ncx_item = next(
        (
            item
            for item in items
            if (item.get_name() or "").lower().endswith(".ncx")
        ),
        None,
    )
    if ncx_item is None:
        return entries
    try:
        raw = ncx_item.get_content().decode("utf-8", errors="replace")
        root = ElementTree.fromstring(raw)
    except Exception:
        return entries

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    def walk(node, depth: int, ancestors: tuple[str, ...]) -> None:
        for child in list(node):
            if local(child.tag) != "navPoint":
                continue
            label = ""
            href = ""
            for sub in child:
                name = local(sub.tag)
                if name == "navLabel":
                    text_el = next((el for el in sub if local(el.tag) == "text"), None)
                    if text_el is not None and text_el.text:
                        label = " ".join(text_el.text.split())
                elif name == "content":
                    href = sub.attrib.get("src") or ""
            if href and label:
                entries.append((href, label, depth, ancestors))
            next_ancestors = ancestors + ((label,) if label else ())
            walk(child, depth + 1, next_ancestors)

    nav_map = next((el for el in root.iter() if local(el.tag) == "navMap"), root)
    walk(nav_map, 1, ())
    return entries


def _toc_full_path(
    toc: tuple[str, int, tuple[str, ...]] | None,
    chapter_title: str,
) -> tuple[list[str], bool]:
    """Return (path titles root→leaf, from_toc)."""
    if toc is None:
        title = (chapter_title or "").strip()
        return ([title] if title else [], False)
    leaf = (toc[0] or chapter_title or "").strip()
    if not leaf:
        return ([], False)
    ancestors = [item for item in toc[2] if item]
    return ([*ancestors, leaf], True)


def _path_delta_markers(
    open_path: list[str],
    full_path: list[str],
    *,
    from_toc: bool,
) -> list[tuple[int, str]]:
    """(level, title) for the divergent suffix. Flat spine chapters stay level 1."""
    common = 0
    while (
        common < len(open_path)
        and common < len(full_path)
        and open_path[common] == full_path[common]
    ):
        common += 1
    markers: list[tuple[int, str]] = []
    flat = not from_toc and len(full_path) == 1
    for index in range(common, len(full_path)):
        level = 1 if flat else index
        markers.append((level, full_path[index]))
    return markers


def _join_heading_block(markers: list[tuple[int, str]], body: str) -> tuple[str, int]:
    """Build spine block text and body offset within the block."""
    if not markers:
        return body, 0
    lines = [heading_marker(title, level) for level, title in markers]
    leaf = lines[-1]
    stripped = body.lstrip()
    if stripped.startswith(leaf):
        prefix = lines[:-1]
        if prefix:
            block = "\n".join([*prefix, stripped])
            return block, sum(len(p) + 1 for p in prefix)
        return stripped, 0
    prefix = lines[:-1]
    heading_line = f"{leaf}\n"
    if prefix:
        block = "\n".join([*prefix, f"{leaf}\n{body}"])
        return block, sum(len(p) + 1 for p in prefix) + len(heading_line)
    return f"{leaf}\n{body}", len(heading_line)


def _html_to_text(html: str) -> str:
    try:
        text, _metadata = parse_html_document(html)
        return text
    except ValueError:
        return ""


def _html_to_text_with_images(
    html: str,
) -> tuple[str, list[dict]]:
    try:
        text, _metadata, images = parse_html_document_with_images(html)
        return text, images
    except ValueError:
        return "", []


def _page_image_items(book, documents: list[tuple[str, str]]) -> list:
    """Resolve page images referenced by spine documents, preserving DOM order."""
    by_href = {
        _normalize_href(item.get_name() or ""): item
        for item in book.get_items()
        if item.get_name()
    }
    pages: list = []
    seen: set[str] = set()
    for document_href, raw_html in documents:
        parser = _PageImageParser()
        try:
            parser.feed(raw_html)
            parser.close()
        except Exception:
            continue
        base = dirname((document_href or "").replace("\\", "/"))
        for source in parser.sources:
            resolved = normpath(join(base, source)).lstrip("./")
            item = book.get_item_with_href(resolved) or by_href.get(_normalize_href(resolved))
            if item is None:
                continue
            key = item.get_id() or item.get_name()
            if not key or key in seen:
                continue
            seen.add(key)
            pages.append(item)
    return pages


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


def load_epub(
    path: Path,
    *,
    on_progress: OcrProgressCallback | None = None,
    settings: Settings | None = None,
    cancel_event: threading.Event | None = None,
) -> tuple[str, dict]:
    try:
        import ebooklib
        from ebooklib import epub
    except ImportError as e:
        raise RuntimeError("EPUB support requires ebooklib: pip install ebooklib") from e

    book = epub.read_epub(str(path))
    title = (book.get_metadata("DC", "title") or [[None]])[0][0]
    author = (book.get_metadata("DC", "creator") or [[None]])[0][0]

    skipped_chapters = 0
    landmark_lookup = _epub_landmark_roles(book)
    toc_lookup = _epub_nested_toc(book)
    # (item, href, raw_html, body, doc_images)
    documents: list[tuple[object, str, str, str, list[dict]]] = []

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
        body, doc_images = _html_to_text_with_images(raw_html)
        documents.append((item, href, raw_html, body, doc_images))

    metadata: dict = {"title": title, "author": author}
    if skipped_chapters:
        metadata["skipped_chapters"] = skipped_chapters

    page_items = _page_image_items(
        book,
        [(href, raw_html) for _item, href, raw_html, _body, _imgs in documents],
    )
    extracted_chars = sum(
        len(body.strip()) for _item, _href, _raw, body, _imgs in documents
    )
    image_ocr_threshold = max(500, len(page_items) * 5)
    if page_items and extracted_chars < image_ocr_threshold:
        images = (
            (page_num, item.get_content())
            for page_num, item in enumerate(page_items, start=1)
        )
        result = ocr_images(
            images,
            total=len(page_items),
            settings=settings,
            on_progress=on_progress,
            cancel_event=cancel_event,
        )
        text = ocr_result_text(result)
        if not text.strip():
            raise RuntimeError("图片型 EPUB OCR 失败或内容为空")
        metadata.update(ocr_metadata_from_result(result))
        metadata["ocr"] = True
        metadata["ocr_source"] = "epub_images"
        metadata["epub_image_pages"] = len(page_items)
        metadata["illustrations_status"] = "skipped_ocr"
        return text, metadata

    parts: list[str] = []
    structure_roles: list[dict] = []
    open_path: list[str] = []
    illustrations: list[dict] = []
    absolute_cursor = 0

    for item, href, raw_html, body, doc_images in documents:
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
        toc = toc_lookup.get(_normalize_href(href))
        full_path, from_toc = _toc_full_path(toc, chapter_title)
        if not full_path:
            full_path, from_toc = ([chapter_title], False) if chapter_title else ([], False)
        delta = _path_delta_markers(open_path, full_path, from_toc=from_toc)
        for _level, title in delta[:-1]:
            structure_roles.append(
                {"title": title, "role": classify_heading(title).value}
            )
        block, body_offset_in_block = _join_heading_block(delta, body)
        if full_path:
            open_path = full_path
        if parts:
            absolute_cursor += 2  # "\n\n".join separator
        for hit in doc_images:
            illustrations.append(
                {
                    **hit,
                    "doc_href": href,
                    "offset": absolute_cursor + body_offset_in_block + int(hit["offset"]),
                }
            )
        parts.append(block)
        absolute_cursor += len(block)
        leaf_title = full_path[-1] if full_path else chapter_title
        role = (landmark[0] if landmark else None) or classify_heading(leaf_title)
        if delta:
            structure_roles.append({"title": delta[-1][1], "role": role.value})
        elif leaf_title:
            structure_roles.append({"title": leaf_title, "role": role.value})

    if skipped_chapters:
        metadata["skipped_chapters"] = skipped_chapters
    if structure_roles:
        metadata["structure_roles"] = structure_roles
    if illustrations:
        metadata["illustrations"] = illustrations
        metadata["illustrations_status"] = "pending"
    else:
        metadata["illustrations_status"] = "none"

    return "\n\n".join(parts), metadata
