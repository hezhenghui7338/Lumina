"""Standalone HTML/XHTML ingestion."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, ClassVar

from lumina_core.ingest.text import decode_text_bytes


def _read_html(path: Path) -> str:
    return decode_text_bytes(path.read_bytes())


class _DocumentParser(HTMLParser):
    _BLOCK_TAGS: ClassVar[set[str]] = {
        "address",
        "article",
        "aside",
        "blockquote",
        "div",
        "footer",
        "header",
        "li",
        "main",
        "p",
        "pre",
        "section",
        "table",
        "tr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.metadata: dict[str, Any] = {}
        self._hidden_depth = 0
        self._title_depth = 0
        self._heading_depth = 0
        self._heading_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_dict = {key.lower(): value for key, value in attrs}
        if tag in {"script", "style", "noscript", "template"}:
            self._hidden_depth += 1
            return
        if self._hidden_depth:
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
        elif tag == "br" or tag in self._BLOCK_TAGS:
            self.parts.append("\n")

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
                self.parts.append(f"\n\n## [§{heading}]\n")
                self.metadata.setdefault("title", heading)
            self._heading_depth -= 1
            self._heading_parts = []
        elif tag in self._BLOCK_TAGS:
            self.parts.append("\n")

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


def load_html(path: Path) -> tuple[str, dict[str, Any]]:
    try:
        return parse_html_document(_read_html(path))
    except (UnicodeError, OSError) as exc:
        raise ValueError("Unable to read HTML document") from exc
