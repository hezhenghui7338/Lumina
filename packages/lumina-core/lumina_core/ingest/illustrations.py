"""EPUB inline illustrations — store beside raw_text, never inside it."""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
import struct
import uuid
from pathlib import Path
from posixpath import dirname, join, normpath
from typing import Any
from urllib.parse import unquote

from lumina_core.chunker.chunker import ChunkSegment
from lumina_core.chunker.coop import GilYielder

logger = logging.getLogger(__name__)

_DECORATIVE_NAME = re.compile(
    r"(?:^|[/_\-.\s])(?:icon|bullet|ornament|decoration|separator|spacer|"
    r"border|background|bg|dropcap|fn|footnote)(?:[/_\-.\s]|$)",
    re.IGNORECASE,
)
_COVER_NAME = re.compile(r"(?:^|[/_\-.\s])cover(?:[/_\-.\s]|$)", re.IGNORECASE)
_BG_CLASS = re.compile(
    r"background|bg[-_\s]|wallpaper|icon|bullet|ornament|decorative|spacer|separator",
    re.IGNORECASE,
)
_MIME_EXT = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/bmp": "bmp",
}
_MIN_ILLUSTRATION_EDGE = 96
_MIN_FILE_BYTES = 2_500


def map_illustrations_to_chunks(
    illustrations: list[dict[str, Any]],
    chunks: list[ChunkSegment],
) -> list[dict[str, Any]]:
    """Attach absolute book offsets to segment_idx + char_offset."""
    if not illustrations or not chunks:
        return []
    ordered = sorted(chunks, key=lambda c: c.start_offset)
    mapped: list[dict[str, Any]] = []
    for hit in illustrations:
        offset = int(hit.get("offset") or 0)
        for chunk in ordered:
            if chunk.start_offset <= offset < chunk.end_offset:
                mapped.append(
                    {
                        **hit,
                        "segment_idx": chunk.index,
                        "char_offset": offset - chunk.start_offset,
                    }
                )
                break
            if offset == chunk.end_offset:
                mapped.append(
                    {
                        **hit,
                        "segment_idx": chunk.index,
                        "char_offset": len(chunk.raw_text),
                    }
                )
                break
    return mapped


def map_illustrations_to_joined_segments(
    illustrations: list[dict[str, Any]],
    *,
    extracted_text: str,
    segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Map absolute offsets onto existing segments (silent backfill)."""
    if not illustrations or not segments:
        return []
    ordered = sorted(segments, key=lambda s: int(s["idx"]))
    joined = "".join(str(s.get("raw_text") or "") for s in ordered)
    if joined == extracted_text:
        cursor = 0
        spans: list[tuple[int, int, dict[str, Any]]] = []
        for seg in ordered:
            raw = str(seg.get("raw_text") or "")
            spans.append((cursor, cursor + len(raw), seg))
            cursor += len(raw)
        mapped: list[dict[str, Any]] = []
        for hit in illustrations:
            offset = int(hit.get("offset") or 0)
            placed = False
            for start, end, seg in spans:
                # Prefer the following segment when offset sits on a boundary.
                if start <= offset < end:
                    mapped.append(
                        {
                            **hit,
                            "segment_idx": int(seg["idx"]),
                            "segment_id": seg["id"],
                            "char_offset": offset - start,
                        }
                    )
                    placed = True
                    break
            if not placed and spans and offset >= spans[-1][1]:
                start, end, seg = spans[-1]
                mapped.append(
                    {
                        **hit,
                        "segment_idx": int(seg["idx"]),
                        "segment_id": seg["id"],
                        "char_offset": end - start,
                    }
                )
        return mapped

    # Text drift: locate via short context windows.
    mapped = []
    for hit in illustrations:
        offset = int(hit.get("offset") or 0)
        left = extracted_text[max(0, offset - 48) : offset]
        right = extracted_text[offset : offset + 48]
        needle = (left + right).strip()
        if len(needle) < 8:
            continue
        pos = joined.find(left[-24:] + right[:24]) if left or right else -1
        if pos < 0 and left:
            pos = joined.find(left[-32:])
            if pos >= 0:
                pos += len(left[-32:])
        if pos < 0:
            continue
        cursor = 0
        for seg in ordered:
            raw = str(seg.get("raw_text") or "")
            end = cursor + len(raw)
            if cursor <= pos <= end:
                mapped.append(
                    {
                        **hit,
                        "segment_idx": int(seg["idx"]),
                        "segment_id": seg["id"],
                        "char_offset": pos - cursor,
                    }
                )
                break
            cursor = end
    return mapped


def classify_illustration_role(
    *,
    href: str,
    alt: str,
    class_name: str,
    style: str,
    epub_type: str,
    width: int | None,
    height: int | None,
    byte_size: int,
    sha256: str,
    cover_sha256: str | None,
) -> str:
    """Return illustration | decorative | cover_dup."""
    if cover_sha256 and sha256 == cover_sha256:
        return "cover_dup"
    href_l = (href or "").lower()
    epub_l = (epub_type or "").lower()
    if "cover" in epub_l or _COVER_NAME.search(href_l):
        return "cover_dup"
    blob = f"{class_name} {style} {alt} {href_l}"
    if _BG_CLASS.search(blob) or _DECORATIVE_NAME.search(href_l):
        return "decorative"
    if width is not None and height is not None:
        if width <= _MIN_ILLUSTRATION_EDGE and height <= _MIN_ILLUSTRATION_EDGE:
            return "decorative"
        if max(width, height) < 48:
            return "decorative"
    if byte_size > 0 and byte_size < _MIN_FILE_BYTES:
        if width is None or height is None or max(width or 0, height or 0) < 160:
            return "decorative"
    return "illustration"


def _image_size(data: bytes) -> tuple[int | None, int | None]:
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        w, h = struct.unpack(">II", data[16:24])
        return int(w), int(h)
    if data.startswith(b"\xff\xd8"):
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                break
            marker = data[i + 1]
            if marker in {0xC0, 0xC1, 0xC2}:
                h, w = struct.unpack(">HH", data[i + 5 : i + 9])
                return int(w), int(h)
            if marker == 0xD9:
                break
            length = struct.unpack(">H", data[i + 2 : i + 4])[0]
            i += 2 + length
    if data.startswith(b"GIF8") and len(data) >= 10:
        w, h = struct.unpack("<HH", data[6:10])
        return int(w), int(h)
    return None, None


def _ext_for(name: str, content_type: str | None, data: bytes) -> str | None:
    if data.startswith(b"<svg") or data.startswith(b"<?xml"):
        return None  # skip SVG in v1 reader
    if content_type:
        mapped = _MIME_EXT.get(content_type.lower().split(";")[0].strip())
        if mapped:
            return mapped
    suffix = Path(name or "").suffix.lower().lstrip(".")
    if suffix in {"jpg", "jpeg", "png", "gif", "webp", "bmp"}:
        return "jpg" if suffix == "jpeg" else suffix
    if data.startswith(b"\x89PNG"):
        return "png"
    if data.startswith(b"\xff\xd8"):
        return "jpg"
    if data.startswith(b"GIF8"):
        return "gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    return None


def _normalize_href(href: str) -> str:
    cleaned = unquote((href or "").split("#", 1)[0]).replace("\\", "/").lstrip("./")
    return cleaned.lower()


def _resolve_epub_item(book, doc_href: str, image_href: str):
    base = dirname((doc_href or "").replace("\\", "/"))
    resolved = normpath(join(base, image_href)).lstrip("./")
    item = book.get_item_with_href(resolved)
    if item is not None:
        return item, resolved
    by_href = {
        _normalize_href(i.get_name() or ""): i
        for i in book.get_items()
        if i.get_name()
    }
    return by_href.get(_normalize_href(resolved)), resolved


def _cover_sha256(book_dir: Path, cover_path: str | None) -> str | None:
    if not cover_path:
        return None
    path = book_dir / cover_path if not Path(cover_path).is_absolute() else Path(cover_path)
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def persist_epub_illustrations(
    conn: sqlite3.Connection,
    *,
    book_id: str,
    epub_path: Path,
    book_dir: Path,
    mapped: list[dict[str, Any]],
    cover_path: str | None = None,
    segments_by_idx: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Write illustration assets + segment anchors. Idempotent per book."""
    from lumina_core.db.repos import BookRepo

    status = {
        "illustrations_status": "ready",
        "illustration_count": 0,
        "illustration_skipped": 0,
    }
    if not mapped:
        BookRepo(conn).update(
            book_id,
            illustrations_status="none",
        )
        status["illustrations_status"] = "none"
        return status

    try:
        from ebooklib import epub
    except ImportError:
        BookRepo(conn).update(book_id, illustrations_status="error")
        status["illustrations_status"] = "error"
        return status

    book = epub.read_epub(str(epub_path))
    cover_hash = _cover_sha256(book_dir, cover_path)
    assets_dir = book_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    coop = GilYielder()

    # Replace any previous illustration index for this book.
    conn.execute(
        "DELETE FROM segment_illustrations WHERE book_id = ?", (book_id,)
    )
    conn.execute("DELETE FROM book_assets WHERE book_id = ?", (book_id,))

    asset_ids: dict[str, str] = {}
    kept = 0
    skipped = 0
    sort_key = 0

    if segments_by_idx is None:
        rows = conn.execute(
            "SELECT id, idx FROM segments WHERE book_id = ? ORDER BY idx",
            (book_id,),
        ).fetchall()
        segments_by_idx = {int(r["idx"]): dict(r) for r in rows}

    for hit in mapped:
        coop.bump(1)
        doc_href = str(hit.get("doc_href") or "")
        image_href = str(hit.get("href") or "")
        item, resolved = _resolve_epub_item(book, doc_href, image_href)
        if item is None:
            skipped += 1
            continue
        try:
            data = bytes(item.get_content())
        except Exception:
            skipped += 1
            continue
        if not data:
            skipped += 1
            continue
        content_type = getattr(item, "media_type", None) or getattr(
            item, "get_type", lambda: None
        )()
        if callable(content_type):
            content_type = None
        ext = _ext_for(resolved, str(content_type) if content_type else None, data)
        if ext is None:
            skipped += 1
            continue
        sha = hashlib.sha256(data).hexdigest()
        decoded_w, decoded_h = _image_size(data)
        width = hit.get("width") or decoded_w
        height = hit.get("height") or decoded_h
        role = classify_illustration_role(
            href=resolved,
            alt=str(hit.get("alt") or ""),
            class_name=str(hit.get("class_name") or ""),
            style=str(hit.get("style") or ""),
            epub_type=str(hit.get("epub_type") or ""),
            width=int(width) if width is not None else None,
            height=int(height) if height is not None else None,
            byte_size=len(data),
            sha256=sha,
            cover_sha256=cover_hash,
        )
        if role != "illustration":
            skipped += 1
            continue

        asset_id = asset_ids.get(sha)
        if asset_id is None:
            asset_id = str(uuid.uuid4())
            rel = f"assets/{sha[:16]}.{ext}"
            dest = book_dir / rel
            if not dest.is_file():
                dest.write_bytes(data)
            mime = {
                "jpg": "image/jpeg",
                "png": "image/png",
                "gif": "image/gif",
                "webp": "image/webp",
                "bmp": "image/bmp",
            }.get(ext, "application/octet-stream")
            conn.execute(
                """
                INSERT INTO book_assets (
                  id, book_id, sha256, rel_path, mime, width, height,
                  byte_size, source_href, role
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset_id,
                    book_id,
                    sha,
                    rel,
                    mime,
                    int(width) if width is not None else None,
                    int(height) if height is not None else None,
                    len(data),
                    resolved,
                    role,
                ),
            )
            asset_ids[sha] = asset_id

        seg_idx = int(hit["segment_idx"])
        seg = segments_by_idx.get(seg_idx)
        if not seg:
            skipped += 1
            continue
        segment_id = hit.get("segment_id") or seg["id"]
        conn.execute(
            """
            INSERT INTO segment_illustrations (
              id, book_id, segment_id, segment_idx, asset_id,
              char_offset, sort_key, alt_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                book_id,
                segment_id,
                seg_idx,
                asset_id,
                int(hit.get("char_offset") or 0),
                sort_key,
                str(hit.get("alt") or "") or None,
            ),
        )
        sort_key += 1
        kept += 1

    conn.commit()
    final_status = "ready" if kept else "none"
    BookRepo(conn).update(book_id, illustrations_status=final_status)
    status["illustrations_status"] = final_status
    status["illustration_count"] = kept
    status["illustration_skipped"] = skipped
    return status


def extract_epub_illustration_hits(epub_path: Path) -> tuple[str, list[dict[str, Any]], str]:
    """Re-load EPUB text + illustration hits for silent backfill.

    Returns (text, hits, status) where status is ready|skipped_ocr|none|error.
    """
    from lumina_core.ingest.epub import load_epub

    try:
        text, metadata = load_epub(epub_path)
    except Exception:
        logger.debug("illustration extract failed for %s", epub_path, exc_info=True)
        return "", [], "error"
    if metadata.get("ocr_source") == "epub_images" or metadata.get("ocr"):
        return text, [], "skipped_ocr"
    hits = list(metadata.get("illustrations") or [])
    if not hits:
        return text, [], "none"
    return text, hits, "ready"


def backfill_book_illustrations(
    conn: sqlite3.Connection,
    book: dict[str, Any],
) -> str:
    """Silent backfill for one already-imported EPUB. Returns new status."""
    from lumina_core.db.repos import BookRepo, SegmentRepo

    book_id = str(book["id"])
    fmt = str(book.get("format") or "").lower()
    if fmt not in {"epub", "mobi", "azw", "azw3"}:
        BookRepo(conn).update(book_id, illustrations_status="none")
        return "none"
    file_path = book.get("file_path")
    if not file_path:
        BookRepo(conn).update(book_id, illustrations_status="none")
        return "none"
    epub_path = Path(str(file_path))
    # MOBI library copy may still be .azw3; load_epub only accepts epub bytes.
    if fmt != "epub":
        # Prefer a sibling .epub if unpack left one; otherwise skip (mobi path
        # already converted text at ingest without illustration hits historically).
        sibling = epub_path.with_suffix(".epub")
        if sibling.is_file():
            epub_path = sibling
        else:
            BookRepo(conn).update(book_id, illustrations_status="none")
            return "none"
    if not epub_path.is_file():
        BookRepo(conn).update(book_id, illustrations_status="none")
        return "none"

    text, hits, status = extract_epub_illustration_hits(epub_path)
    if status != "ready":
        BookRepo(conn).update(book_id, illustrations_status=status)
        return status

    segments = SegmentRepo(conn).list_for_book(book_id, include_body=True, include_summary=False)
    mapped = map_illustrations_to_joined_segments(
        hits, extracted_text=text, segments=segments
    )
    result = persist_epub_illustrations(
        conn,
        book_id=book_id,
        epub_path=epub_path,
        book_dir=epub_path.parent,
        mapped=mapped,
        cover_path=book.get("cover_path"),
        segments_by_idx={int(s["idx"]): s for s in segments},
    )
    return str(result["illustrations_status"])


def list_segment_illustrations(
    conn: sqlite3.Connection, book_id: str, segment_idx: int
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT si.char_offset, si.alt_text, si.sort_key,
               a.id AS asset_id, a.rel_path, a.mime, a.width, a.height
        FROM segment_illustrations si
        JOIN book_assets a ON a.id = si.asset_id
        WHERE si.book_id = ? AND si.segment_idx = ? AND a.role = 'illustration'
        ORDER BY si.char_offset ASC, si.sort_key ASC
        """,
        (book_id, segment_idx),
    ).fetchall()
    return [
        {
            "char_offset": int(r["char_offset"]),
            "alt": r["alt_text"] or "",
            "asset_id": r["asset_id"],
            "mime": r["mime"],
            "width": r["width"],
            "height": r["height"],
            "url": f"/books/{book_id}/assets/{r['asset_id']}",
        }
        for r in rows
    ]
