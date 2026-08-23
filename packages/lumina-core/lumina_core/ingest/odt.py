"""OpenDocument Text ingestion via odfpy."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def load_odt(path: Path) -> tuple[str, dict[str, Any]]:
    try:
        from odf import dc, teletype, text
        from odf.opendocument import load
    except ImportError as exc:
        raise RuntimeError("ODT support requires odfpy: pip install odfpy") from exc

    try:
        document = load(str(path))
    except Exception as exc:
        raise ValueError("Invalid or encrypted ODT document") from exc

    parts: list[str] = []
    for node in document.text.childNodes:
        tag_name = getattr(node, "tagName", "")
        if tag_name == "text:h":
            value = teletype.extractText(node).strip()
            if value:
                parts.append(f"## [§{value}]")
        elif tag_name == "text:p":
            value = teletype.extractText(node).strip()
            if value:
                parts.append(value)
        else:
            for paragraph in node.getElementsByType(text.P):
                value = teletype.extractText(paragraph).strip()
                if value:
                    parts.append(value)

    content = "\n\n".join(parts).strip()
    if not content:
        raise ValueError("ODT document contains no readable text")

    metadata: dict[str, Any] = {}
    titles = document.meta.getElementsByType(dc.Title)
    creators = document.meta.getElementsByType(dc.Creator)
    if titles:
        title = teletype.extractText(titles[0]).strip()
        if title:
            metadata["title"] = title
    if creators:
        author = teletype.extractText(creators[0]).strip()
        if author:
            metadata["author"] = author
    return content, metadata
