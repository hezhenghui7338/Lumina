"""Persist streamed TXT segments without holding the whole book in RAM."""

from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Any

from lumina_core.chunker.stream import iter_txt_chunks
from lumina_core.chunker.coop import CharProgressFn, coerce_char_progress
from lumina_core.config import (
    CHUNKER_VERSION,
    ModelsConfig,
    normalize_segment_tier,
    resolve_chunk_budget,
)
from lumina_core.db.connection import detach_db_lock
from lumina_core.db.repos import BookRepo, SegmentRepo, resolve_ingest_title
from lumina_core.db.schema import connect_db
from lumina_core.ingest.loader import author_from_metadata, title_from_path
from lumina_core.ingest.progress import DocumentLoadCancelled
from lumina_core.search.fts import index_book
from lumina_core.translate.language import infer_language

_LANG_SAMPLE_CHARS = 8_000


def _chunk_to_row(book_id: str, chunk) -> dict[str, Any]:
    anchor = f"段 {chunk.index + 1}"
    if chunk.chapter:
        anchor = f"{chunk.chapter} · 段 {chunk.index + 1}"
    if chunk.page_range:
        anchor = f"{anchor} · {chunk.page_range}"
    return {
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


def persist_streamed_txt_ingest(
    db_path: Path,
    *,
    book_id: str,
    dest: Path,
    src: Path,
    models: ModelsConfig | None,
    metadata: dict[str, Any],
    target_language: str,
    segment_tier: str,
    cancel_event: threading.Event,
    on_progress: CharProgressFn | None = None,
    chunk_target_chars: int | None = None,
) -> tuple[int, dict[str, Any], str | None]:
    """Decode/chunk/insert TXT in windows. Returns (segment_count, ingest_meta, language)."""
    if cancel_event.is_set():
        raise DocumentLoadCancelled("已取消")
    budget = (
        resolve_chunk_budget(target_chars=chunk_target_chars)
        if chunk_target_chars is not None
        else resolve_chunk_budget(models)
    )
    conn = connect_db(db_path)
    try:
        books_repo = BookRepo(conn)
        if not books_repo.get(book_id):
            return 0, {}, None
        repo = SegmentRepo(conn)
        batch: list[dict[str, Any]] = []
        count = 0
        total_chars = 0
        lang_parts: list[str] = []
        plan_label = "utf-8"
        last_end = 0
        last_page = 0
        last_total = 1
        report = coerce_char_progress(on_progress)

        def on_stream_progress(page: int, total: int, message: str) -> None:
            nonlocal last_page, last_total
            last_page = page
            last_total = max(total, 1)
            if report is not None:
                report(page, last_total, message)

        def flush_batch() -> None:
            nonlocal batch, count
            if not batch:
                return
            repo.insert_many(batch)
            count += len(batch)
            batch = []

        try:
            for plan, chunk in iter_txt_chunks(
                dest,
                budget=budget,
                cancel_event=cancel_event,
                on_progress=on_stream_progress,
            ):
                if cancel_event.is_set():
                    raise DocumentLoadCancelled("已取消")
                plan_label = plan.label
                if chunk.index == 0 and chunk.start_offset != 0:
                    raise RuntimeError("首段偏移必须为 0")
                if chunk.start_offset != last_end:
                    raise RuntimeError("分段偏移必须首尾相接")
                last_end = chunk.end_offset
                total_chars += len(chunk.raw_text)
                if sum(len(part) for part in lang_parts) < _LANG_SAMPLE_CHARS:
                    lang_parts.append(chunk.raw_text[:_LANG_SAMPLE_CHARS])
                batch.append(_chunk_to_row(book_id, chunk))
                if len(batch) >= 200:
                    flush_batch()
                    if report is not None:
                        report(last_page, last_total, "正在写入书库…")
        except InterruptedError as exc:
            raise DocumentLoadCancelled("已取消") from exc

        flush_batch()
        if count == 0:
            raise RuntimeError("文档无可提取文本")
        ingest_meta = dict(metadata)
        ingest_meta.pop("document_tree", None)
        ingest_meta["total_char_count"] = total_chars
        ingest_meta["chunker_version"] = CHUNKER_VERSION
        ingest_meta["chunk_target_chars"] = budget.target_chars
        ingest_meta["segment_tier"] = normalize_segment_tier(segment_tier)
        ingest_meta["text_encoding"] = plan_label
        language = infer_language("".join(lang_parts)[:_LANG_SAMPLE_CHARS])
        book_row = books_repo.get(book_id)
        if not book_row:
            return 0, {}, None
        title = resolve_ingest_title(book_row, title_from_path(src, metadata), ingest_meta)
        repo.complete_ingest(
            book_id,
            title=title,
            author=author_from_metadata(metadata),
            language=language,
            target_language=target_language,
            metadata_json=ingest_meta,
            segment_count=count,
        )
        book_row = books_repo.get(book_id)
        if book_row:
            index_book(conn, book_row)
        repo.backfill_char_counts(book_id)
        return count, ingest_meta, language
    finally:
        conn.close()
        detach_db_lock(conn)


def persist_streamed_txt_resegment(
    db_path: Path,
    *,
    book_id: str,
    dest: Path,
    chunk_target_chars: int,
    old_metadata: dict[str, Any],
    final_status: str,
    segment_tier: str,
    cancel_event: threading.Event,
    on_progress: CharProgressFn | None = None,
) -> tuple[int, dict[str, Any]]:
    """Stage new TXT segments, then atomically replace the book's rows."""
    if cancel_event.is_set():
        raise DocumentLoadCancelled("已取消")
    budget = resolve_chunk_budget(target_chars=chunk_target_chars)
    conn = connect_db(db_path)
    try:
        repo = SegmentRepo(conn)
        repo.begin_segment_staging()
        batch: list[dict[str, Any]] = []
        count = 0
        total_chars = 0
        plan_label = "utf-8"
        last_end = 0
        last_page = 0
        last_total = 1
        report = coerce_char_progress(on_progress)

        def on_stream_progress(page: int, total: int, message: str) -> None:
            nonlocal last_page, last_total
            last_page = page
            last_total = max(total, 1)
            if report is not None:
                report(page, last_total, message)

        def flush_batch() -> None:
            nonlocal batch, count
            if not batch:
                return
            repo.insert_staging(batch)
            count += len(batch)
            batch = []

        try:
            for plan, chunk in iter_txt_chunks(
                dest,
                budget=budget,
                cancel_event=cancel_event,
                on_progress=on_stream_progress,
            ):
                if cancel_event.is_set():
                    raise DocumentLoadCancelled("已取消")
                plan_label = plan.label
                if chunk.start_offset != last_end:
                    raise RuntimeError("分段偏移必须首尾相接")
                last_end = chunk.end_offset
                total_chars += len(chunk.raw_text)
                batch.append(_chunk_to_row(book_id, chunk))
                if len(batch) >= 200:
                    flush_batch()
                    if report is not None:
                        report(last_page, last_total, "正在写入书库…")
        except InterruptedError as exc:
            raise DocumentLoadCancelled("已取消") from exc
        if cancel_event.is_set():
            raise DocumentLoadCancelled("已取消")
        flush_batch()
        if cancel_event.is_set():
            raise DocumentLoadCancelled("已取消")
        if count == 0:
            raise RuntimeError("文档无可提取文本")
        metadata = dict(old_metadata)
        metadata.pop("document_tree", None)
        metadata["total_char_count"] = total_chars
        metadata["chunker_version"] = CHUNKER_VERSION
        metadata["chunk_target_chars"] = chunk_target_chars
        metadata["segment_tier"] = normalize_segment_tier(segment_tier)
        metadata["text_encoding"] = plan_label
        metadata.pop("resegment_error", None)
        metadata.pop("document_tree", None)
        if cancel_event.is_set():
            raise DocumentLoadCancelled("已取消")
        repo.commit_staging_replace(
            book_id,
            metadata_json=metadata,
            status=final_status,
            segment_count=count,
        )
        return count, metadata
    finally:
        conn.close()
        detach_db_lock(conn)
