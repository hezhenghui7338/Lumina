"""Standalone HTML/XHTML ingestion."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import unquote

from lumina_core.chunker.markers import heading_marker
from lumina_core.ingest.text import decode_text_bytes

# Private-use markers keep illustration offsets aligned with cleaned text
# without leaking into the final raw_text returned to callers.
_IMG_MARK_RE = re.compile("\ue000([0-9a-f]{4})\ue001")


def _read_html(path: Path) -> str:
    return decode_text_bytes(path.read_bytes())


def _parse_dimension(value: str | None) -> int | None:
    if not value:
        return None
    match = re.match(r"^\s*(\d+(?:\.\d+)?)", value)
    if not match:
        return None
    try:
        return max(0, int(float(match.group(1))))
    except ValueError:
        return None


class _DocumentParser(HTMLParser):
    # Real paragraphs / breaks → blank-line-ish separation after _clean_document.
    _HARD_BLOCK_TAGS: ClassVar[set[str]] = {
        "blockquote",
        "li",
        "p",
        "pre",
        "table",
        "tr",
    }
    # Layout wrappers common in EPUB/XHTML. Emitting \n on both sides turned
    # every <div class="para"> into a blank row in the reader. Match the old
    # EPUB regex (non-p tags → space) so adjacent wrappers do not invent \n\n.
    _SOFT_BLOCK_TAGS: ClassVar[set[str]] = {
        "address",
        "article",
        "aside",
        "div",
        "footer",
        "header",
        "main",
        "section",
    }

    def __init__(self, *, capture_images: bool = False) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.metadata: dict[str, Any] = {}
        self._hidden_depth = 0
        self._title_depth = 0
        self._heading_depth = 0
        self._heading_parts: list[str] = []
        self._capture_images = capture_images
        self._pending_images: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_dict = {key.lower(): value for key, value in attrs}
        if tag in {"script", "style", "noscript", "template"}:
            self._hidden_depth += 1
            return
        if self._hidden_depth:
            return
        if self._capture_images and tag in {"img", "image"} and not self._title_depth:
            self._emit_image(attrs_dict)
            return
        if tag == "meta":
            name = (attrs_dict.get("name") or attrs_dict.get("property") or "").lower()
            content = (attrs_dict.get("content") or "").strip()
            if name in {"author", "dc.creator", "article:author"} and content:
                self.metadata.setdefault("author", content)
            if name in {"title", "dc.title", "og:title"} and content:
                self.metadata.setdefault("title", content)
        elif tag == "title":
            self._title_depth += 1
        elif re.fullmatch(r"h[1-6]", tag):
            self._heading_depth += 1
            self._heading_parts = []
        elif tag == "br" or tag in self._HARD_BLOCK_TAGS:
            self.parts.append("\n")
        elif tag in self._SOFT_BLOCK_TAGS:
            self.parts.append(" ")

    def _emit_image(self, attrs: dict[str, str | None]) -> None:
        source = (
            attrs.get("src")
            or attrs.get("href")
            or attrs.get("xlink:href")
            or ""
        ).strip()
        if not source or source.startswith(("data:", "http://", "https://")):
            return
        idx = len(self._pending_images)
        self._pending_images.append(
            {
                "href": unquote(source.split("#", 1)[0]),
                "alt": (attrs.get("alt") or "").strip(),
                "class_name": (attrs.get("class") or "").strip(),
                "style": (attrs.get("style") or "").strip(),
                "epub_type": (
                    attrs.get("epub:type") or attrs.get("type") or ""
                ).strip(),
                "width": _parse_dimension(attrs.get("width")),
                "height": _parse_dimension(attrs.get("height")),
            }
        )
        self.parts.append(f"\ue000{idx:04x}\ue001")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "template"}:
            self._hidden_depth = max(0, self._hidden_depth - 1)
            return
        if self._hidden_depth:
            return
        if tag == "title":
            self._title_depth = max(0, self._title_depth - 1)
        elif re.fullmatch(r"h[1-6]", tag) and self._heading_depth:
            heading = _clean_inline("".join(self._heading_parts))
            if heading:
                self.parts.append(f"\n\n{heading_marker(heading, int(tag[1]))}\n")
                self.metadata.setdefault("title", heading)
            self._heading_depth -= 1
            self._heading_parts = []
        elif tag in self._HARD_BLOCK_TAGS:
            self.parts.append("\n")
        elif tag in self._SOFT_BLOCK_TAGS:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self._hidden_depth:
            return
        if self._title_depth:
            self.title_parts.append(data)
        elif self._heading_depth:
            self._heading_parts.append(data)
        else:
            self.parts.append(data)

    def result(self) -> tuple[str, dict[str, Any]]:
        title = _clean_inline("".join(self.title_parts))
        if title:
            self.metadata["title"] = title
        text = _clean_document("".join(self.parts))
        if not text:
            raise ValueError("HTML document contains no readable text")
        return text, self.metadata

    def result_with_images(self) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        title = _clean_inline("".join(self.title_parts))
        if title:
            self.metadata["title"] = title
        marked = _clean_document("".join(self.parts))
        text, images = _strip_image_markers(marked, self._pending_images)
        if not text and not images:
            raise ValueError("HTML document contains no readable text")
        return text, self.metadata, images


def _strip_image_markers(
    marked: str, pending: list[dict[str, Any]]
) -> tuple[str, list[dict[str, Any]]]:
    """Remove private-use markers and return cleaned text + offset hits."""
    if not pending:
        return marked, []
    unmarked = _IMG_MARK_RE.sub("", marked)
    cleaned, index_map = _clean_document_mapped(unmarked)
    images: list[dict[str, Any]] = []
    removed = 0
    for match in _IMG_MARK_RE.finditer(marked):
        idx = int(match.group(1), 16)
        if 0 <= idx < len(pending):
            unmarked_offset = match.start() - removed
            mapped = (
                index_map[unmarked_offset]
                if unmarked_offset < len(index_map)
                else len(cleaned)
            )
            hit = dict(pending[idx])
            hit["offset"] = min(max(0, mapped), len(cleaned))
            images.append(hit)
        removed += match.end() - match.start()
    return cleaned, images


def _clean_document_mapped(value: str) -> tuple[str, list[int]]:
    """Like _clean_document, plus map from old index → cleaned index."""
    # Normalize newlines first (same as _clean_document).
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    # Build cleaned string char-by-char while recording origins.
    chars: list[str] = []
    origins: list[int] = []
    i = 0
    n = len(normalized)
    while i < n:
        ch = normalized[i]
        if ch in " \t\f\v":
            if chars and chars[-1] == " ":
                i += 1
                continue
            # Peek: spaces before newline are dropped by " *\n *"
            j = i
            while j < n and normalized[j] in " \t\f\v":
                j += 1
            if j < n and normalized[j] == "\n":
                i = j
                continue
            chars.append(" ")
            origins.append(i)
            i += 1
            continue
        if ch == "\n":
            # Skip spaces after newline
            chars.append("\n")
            origins.append(i)
            i += 1
            while i < n and normalized[i] in " \t\f\v":
                i += 1
            # Collapse \n{3,} later
            continue
        chars.append(ch)
        origins.append(i)
        i += 1

    # Collapse \n{3,} → \n\n
    out_c: list[str] = []
    out_o: list[int] = []
    i = 0
    while i < len(chars):
        if chars[i] == "\n":
            run = 0
            start_o = origins[i]
            while i < len(chars) and chars[i] == "\n":
                run += 1
                i += 1
            out_c.append("\n")
            out_o.append(start_o)
            if run >= 2:
                out_c.append("\n")
                out_o.append(start_o)
            continue
        out_c.append(chars[i])
        out_o.append(origins[i])
        i += 1
    chars, origins = out_c, out_o

    # strip
    start = 0
    end = len(chars)
    while start < end and chars[start].isspace():
        start += 1
    while end > start and chars[end - 1].isspace():
        end -= 1
    chars = chars[start:end]
    origins = origins[start:end]
    cleaned = "".join(chars)

    index_map = [-1] * (len(normalized) + 1)
    for new_i, old_i in enumerate(origins):
        if 0 <= old_i < len(index_map):
            index_map[old_i] = new_i
    next_valid = len(cleaned)
    for i in range(len(index_map) - 1, -1, -1):
        if index_map[i] >= 0:
            next_valid = index_map[i]
        else:
            index_map[i] = next_valid
    return cleaned, index_map


def _clean_inline(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _clean_document(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t\f\v]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def parse_html_document(source: str) -> tuple[str, dict[str, Any]]:
    parser = _DocumentParser()
    parser.feed(source)
    parser.close()
    return parser.result()


def parse_html_document_with_images(
    source: str,
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    """Like parse_html_document, plus illustration hits with char offsets."""
    parser = _DocumentParser(capture_images=True)
    parser.feed(source)
    parser.close()
    return parser.result_with_images()


def load_html(path: Path) -> tuple[str, dict[str, Any]]:
    try:
        return parse_html_document(_read_html(path))
    except (UnicodeError, OSError) as exc:
        raise ValueError("Unable to read HTML document") from exc
