"""DOCX ingestion via python-docx."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterator

from lumina_core.chunker.markers import heading_marker
from lumina_core.ingest.pipe_table import format_pipe_table


def _paragraph_text(paragraph) -> str:
    return re.sub(r"[ \t]+", " ", paragraph.text).strip()


def _iter_block_items(document) -> Iterator[Any]:
    """Yield paragraphs and tables in document body order."""
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    body = document.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield Table(child, document)


def _table_rows(table) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in table.rows:
        cells = [re.sub(r"\s+", " ", cell.text).strip() for cell in row.cells]
        if any(cells):
            rows.append(cells)
    return rows


def load_docx(path: Path) -> tuple[str, dict[str, Any]]:
    try:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError as exc:
        raise RuntimeError("DOCX support requires python-docx: pip install python-docx") from exc

    try:
        document = Document(str(path))
    except Exception as exc:
        raise ValueError("Invalid or encrypted DOCX document") from exc

    parts: list[str] = []
    for block in _iter_block_items(document):
        if isinstance(block, Paragraph):
            text = _paragraph_text(block)
            if not text:
                continue
            style_name = (getattr(block.style, "name", "") or "").lower()
            if style_name.startswith("heading") or style_name in {"title", "subtitle"}:
                level = 1
                if style_name.startswith("heading"):
                    suffix = style_name.replace("heading", "").strip()
                    if suffix.isdigit():
                        level = max(1, int(suffix))
                parts.append(heading_marker(text, level))
            else:
                parts.append(text)
        elif isinstance(block, Table):
            formatted = format_pipe_table(_table_rows(block), header=True)
            if formatted:
                parts.append(formatted.strip("\n"))

    text = "\n\n".join(p for p in parts if p).strip()
    # Collapse accidental quadruple newlines from table wrappers + join.
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        raise ValueError("DOCX document contains no readable text")

    properties = document.core_properties
    metadata = {
        key: value.strip()
        for key, value in {
            "title": properties.title,
            "author": properties.author,
        }.items()
        if isinstance(value, str) and value.strip()
    }
    return text, metadata
