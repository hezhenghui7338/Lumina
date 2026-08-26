"""Stream a TXT file into reading segments without holding the whole book.

Disk may keep original.txt. RAM is one decode window plus the in-flight segment.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator

from lumina_core.chunker.chunker import ChunkSegment, chunk_text
from lumina_core.chunker.coop import CharProgressFn, GilYielder, ScanProgress, coerce_char_progress
from lumina_core.config import ChunkBudget, resolve_chunk_budget
from lumina_core.ingest.text import (
    EncodingPlan,
    detect_encoding_plan,
    iter_decoded_file,
)

# ~256k characters ≈ 1MB UCS-4. Far below a 13–500MB book.
STREAM_WINDOW_CHARS = 256_000
_SAMPLE_BYTES = 64 * 1024


def detect_txt_plan(path) -> EncodingPlan:
    with path.open("rb") as handle:
        sample = handle.read(_SAMPLE_BYTES)
    return detect_encoding_plan(sample)


def _estimate_total_chars(file_size: int, bytes_read: int, chars_seen: int) -> int:
    if chars_seen <= 0:
        return max(file_size, 1)
    if bytes_read <= 0:
        return max(file_size, chars_seen, 1)
    return max(chars_seen, int(file_size * chars_seen / bytes_read), 1)


def iter_txt_chunks(
    path,
    *,
    budget: ChunkBudget | None = None,
    cancel_event: threading.Event | None = None,
    on_progress: CharProgressFn | None = None,
    window_chars: int = STREAM_WINDOW_CHARS,
) -> Iterator[tuple[EncodingPlan, ChunkSegment]]:
    """Yield (plan, segment) with global offsets. Does not retain finished text."""
    resolved = budget or resolve_chunk_budget()
    plan = detect_txt_plan(path)
    yielder = GilYielder(cancel_event)
    buffer = ""
    saw_content = False
    global_off = 0
    index = 0
    last_chapter: str | None = None
    window = max(resolved.max_chars * 2, window_chars)
    try:
        file_size = max(1, path.stat().st_size)
    except OSError:
        file_size = 1
    bytes_read = 0
    first_window = True
    reporter = coerce_char_progress(on_progress)
    progress = ScanProgress(reporter, file_size, "正在解析文档…")
    progress.emit(0, "正在解析文档…", force=True)

    def on_bytes(read: int, size: int) -> None:
        nonlocal bytes_read, file_size
        bytes_read = read
        file_size = max(size, file_size, 1)
        chars_seen = global_off + len(buffer)
        progress.total = _estimate_total_chars(file_size, bytes_read, chars_seen)
        progress.emit(chars_seen, "正在解析文档…")

    def emit_segments(
        chunks: list[ChunkSegment],
        *,
        keep_tail: bool,
    ) -> Iterator[ChunkSegment]:
        nonlocal buffer, global_off, index, last_chapter
        if not chunks:
            buffer = ""
            return
        if keep_tail and len(chunks) > 1:
            to_emit = chunks[:-1]
            buffer = chunks[-1].raw_text
        else:
            to_emit = chunks
            buffer = ""
        for chunk in to_emit:
            chapter = chunk.chapter or last_chapter
            if chunk.chapter:
                last_chapter = chunk.chapter
            length = len(chunk.raw_text)
            yield ChunkSegment(
                index=index,
                raw_text=chunk.raw_text,
                start_offset=global_off,
                end_offset=global_off + length,
                chapter=chapter,
                page_range=chunk.page_range,
            )
            global_off += length
            index += 1
            yielder.bump(length or 1)

    def chunk_buffer() -> list[ChunkSegment]:
        nonlocal first_window
        message = (
            "正在识别序言与正文结构…"
            if first_window
            else "正在按窗口切分阅读单元…"
        )
        first_window = False
        window_len = max(len(buffer), 1)
        chars_seen = global_off + window_len
        total = _estimate_total_chars(file_size, bytes_read, chars_seen)
        progress.total = total
        progress.emit(global_off, message, force=True)

        def inner(page: int, total_local: int, stage: str) -> None:
            frac = page / max(total_local, window_len, 1)
            done = global_off + min(window_len, max(0, int(frac * window_len)))
            est = _estimate_total_chars(file_size, bytes_read, global_off + window_len)
            if reporter is not None:
                reporter(done, est, stage or message)

        return chunk_text(
            buffer,
            budget=resolved,
            cancel_event=cancel_event,
            on_progress=inner,
            strip_text=False,
        )

    for piece in iter_decoded_file(path, plan=plan, on_bytes=on_bytes):
        yielder.check()
        buffer += piece
        if not saw_content:
            buffer = buffer.lstrip()
            if buffer:
                saw_content = True
        while saw_content and len(buffer) >= window:
            chunks = chunk_buffer()
            if len(chunks) <= 1:
                # Rare: one span still longer than the window. Force a cut.
                cut = min(len(buffer), resolved.max_chars)
                if cut <= 0:
                    break
                forced = [
                    ChunkSegment(
                        index=0,
                        raw_text=buffer[:cut],
                        start_offset=0,
                        end_offset=cut,
                    )
                ]
                if cut < len(buffer):
                    forced.append(
                        ChunkSegment(
                            index=1,
                            raw_text=buffer[cut:],
                            start_offset=cut,
                            end_offset=len(buffer),
                        )
                    )
                    yield from (
                        (plan, segment)
                        for segment in emit_segments(forced, keep_tail=True)
                    )
                else:
                    yield from (
                        (plan, segment)
                        for segment in emit_segments(forced, keep_tail=False)
                    )
                continue
            for segment in emit_segments(chunks, keep_tail=True):
                yield plan, segment

    if buffer:
        buffer = buffer.rstrip()
    if buffer:
        chunks = chunk_buffer()
        for segment in emit_segments(chunks, keep_tail=False):
            yield plan, segment
