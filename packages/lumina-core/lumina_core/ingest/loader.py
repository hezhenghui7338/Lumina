"""Document ingestion and format dispatch."""

from __future__ import annotations

import hashlib
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any

from lumina_core.chunker.chunker import ChunkSegment, chunk_text
from lumina_core.chunker.semantic import PairScorer
from lumina_core.config import MAX_FILE_BYTES, ChunkBudget, Settings
from lumina_core.ingest.docx import load_docx
from lumina_core.ingest.epub import load_epub
from lumina_core.ingest.fb2 import load_fb2
from lumina_core.ingest.html import load_html
from lumina_core.ingest.odt import load_odt
from lumina_core.ingest.pdf import load_pdf
from lumina_core.ingest.rtf import load_rtf
from lumina_core.ingest.text import decode_text_bytes, iter_decoded_file

TEXT_EXTENSIONS = {"txt", "text", "md", "markdown", "mdown", "mkd", "log"}
FORMAT_EXTENSIONS = {
    "htm": "html",
    "html": "html",
    "xhtml": "html",
    "rtf": "rtf",
    "docx": "docx",
    "odt": "odt",
    "fb2": "fb2",
    "pdf": "pdf",
    "epub": "epub",
    "mobi": "mobi",
    "azw": "mobi",
    "azw3": "mobi",
}


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def detect_format(path: Path) -> str:
    ext = path.suffix.lower().lstrip(".")
    if ext in TEXT_EXTENSIONS:
        return "txt"
    if ext in FORMAT_EXTENSIONS:
        return FORMAT_EXTENSIONS[ext]
    raise ValueError(f"Unsupported format: {path.suffix}")


def load_txt(path: Path) -> str:
    return "".join(iter_decoded_file(path))


def load_document(
    path: Path,
    fmt: str,
    *,
    on_progress=None,
    settings: Settings | None = None,
    cancel_event: threading.Event | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return (annotated_text, metadata)."""
    if fmt == "txt":
        return load_txt(path), {}
    if fmt == "pdf":
        return load_pdf(
            path,
            on_progress=on_progress,
            settings=settings,
            cancel_event=cancel_event,
        )
    if fmt == "epub":
        return load_epub(path)
    if fmt == "mobi":
        from lumina_core.ingest.mobi import load_mobi

        return load_mobi(path)
    if fmt == "html":
        return load_html(path)
    if fmt == "rtf":
        return load_rtf(path)
    if fmt == "docx":
        return load_docx(path)
    if fmt == "odt":
        return load_odt(path)
    if fmt == "fb2":
        return load_fb2(path)
    raise ValueError(f"Format not implemented: {fmt}")


def validate_import(path: Path) -> None:
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ValueError(f"File exceeds 500MB limit ({size} bytes)")


def copy_to_library(src: Path, books_dir: Path, book_id: str) -> Path:
    dest_dir = books_dir / book_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"original{src.suffix.lower()}"
    shutil.copy2(src, dest)
    return dest


def title_from_path(path: Path, metadata: dict[str, Any] | None = None) -> str:
    if metadata and metadata.get("title"):
        return str(metadata["title"])
    return path.stem or "Untitled"


def author_from_metadata(metadata: dict[str, Any] | None) -> str | None:
    if metadata and metadata.get("author"):
        return str(metadata["author"])
    return None


def build_segments(
    book_id: str,
    text: str,
    *,
    budget: ChunkBudget | None = None,
    scorer: PairScorer | None = None,
    document_map: list | None = None,
    structure_roles: list | None = None,
    chunks: list[ChunkSegment] | None = None,
) -> list[dict]:
    from lumina_core.chunker.coop import GilYielder

    resolved = chunks or chunk_text(
        text,
        budget=budget,
        scorer=scorer,
        document_map=document_map,
        structure_roles=structure_roles,
    )
    coop = GilYielder()
    segments: list[dict] = []
    for chunk in resolved:
        anchor = f"段 {chunk.index + 1}"
        if chunk.chapter:
            anchor = f"{chunk.chapter} · 段 {chunk.index + 1}"
        if chunk.page_range:
            anchor = f"{anchor} · {chunk.page_range}"
        segments.append(
            {
                "id": str(uuid.uuid4()),
                "book_id": book_id,
                "idx": chunk.index,
                "chapter": chunk.chapter,
                "heading_path": list(chunk.heading_path),
                "page_range": chunk.page_range,
                "anchor_label": f"〔{anchor}〕",
                "raw_text": chunk.raw_text,
                "char_count": len(chunk.raw_text),
                "summary_status": "pending",
                "retry_count": 0,
            }
        )
        coop.bump(len(chunk.raw_text) or 1)
    return segments
