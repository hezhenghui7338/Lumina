"""Document ingestion — TXT / PDF / EPUB."""

from __future__ import annotations

import hashlib
import shutil
import uuid
from pathlib import Path
from typing import Any

from lumina_core.chunker.chunker import chunk_text
from lumina_core.config import ChunkBudget, MAX_FILE_BYTES
from lumina_core.ingest.epub import load_epub
from lumina_core.ingest.pdf import load_pdf


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def detect_format(path: Path) -> str:
    ext = path.suffix.lower().lstrip(".")
    if ext in {"txt", "md"}:
        return "txt"
    if ext in {"pdf", "epub", "mobi"}:
        return ext
    raise ValueError(f"Unsupported format: {path.suffix}")


def load_txt(path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def load_document(
    path: Path,
    fmt: str,
    *,
    on_progress=None,
) -> tuple[str, dict[str, Any]]:
    """Return (annotated_text, metadata)."""
    if fmt == "txt":
        return load_txt(path), {}
    if fmt == "pdf":
        return load_pdf(path, on_progress=on_progress)
    if fmt == "epub":
        return load_epub(path)
    if fmt == "mobi":
        from lumina_core.ingest.mobi import load_mobi

        return load_mobi(path)
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


def build_segments(book_id: str, text: str, *, budget: ChunkBudget | None = None) -> list[dict]:
    chunks = chunk_text(text, budget=budget)
    segments: list[dict] = []
    for chunk in chunks:
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
                "page_range": chunk.page_range,
                "anchor_label": f"〔{anchor}〕",
                "raw_text": chunk.raw_text,
                "char_count": len(chunk.raw_text),
                "summary_status": "pending",
                "retry_count": 0,
            }
        )
    return segments
