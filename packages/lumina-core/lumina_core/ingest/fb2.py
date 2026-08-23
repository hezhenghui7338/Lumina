"""FictionBook 2.0 XML ingestion."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from lumina_core.ingest.text import decode_text_bytes


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _element_text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def _first_descendant(root: ET.Element, name: str) -> ET.Element | None:
    return next((node for node in root.iter() if _local_name(node.tag) == name), None)


def _author_name(author: ET.Element | None) -> str | None:
    if author is None:
        return None
    parts: list[str] = []
    for field in ("first-name", "middle-name", "last-name", "nickname"):
        value = _element_text(_first_descendant(author, field))
        if value and value not in parts:
            parts.append(value)
    return " ".join(parts) or None


def _append_content(element: ET.Element, parts: list[str]) -> None:
    name = _local_name(element.tag)
    if name == "title":
        title = _element_text(element)
        if title:
            parts.append(f"## [§{title}]")
        return
    if name in {"p", "subtitle", "text-author"}:
        value = _element_text(element)
        if value:
            parts.append(value)
        return
    if name in {"binary", "description"}:
        return
    for child in element:
        _append_content(child, parts)


def load_fb2(path: Path) -> tuple[str, dict[str, Any]]:
    try:
        root = ET.fromstring(decode_text_bytes(path.read_bytes()))
    except (ET.ParseError, OSError, LookupError) as exc:
        raise ValueError("Invalid FB2 document") from exc
    if _local_name(root.tag) != "FictionBook":
        raise ValueError("Invalid FB2 document")

    description = _first_descendant(root, "description")
    title_info = _first_descendant(description, "title-info") if description is not None else None
    metadata: dict[str, Any] = {}
    title = _element_text(_first_descendant(title_info, "book-title")) if title_info is not None else ""
    author = _author_name(_first_descendant(title_info, "author")) if title_info is not None else None
    if title:
        metadata["title"] = title
    if author:
        metadata["author"] = author

    parts: list[str] = []
    for body in (node for node in root if _local_name(node.tag) == "body"):
        _append_content(body, parts)
    content = "\n\n".join(parts).strip()
    if not content:
        raise ValueError("FB2 document contains no readable text")
    return content, metadata
