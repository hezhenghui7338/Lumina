"""Chunker unit tests."""

from lumina_core.chunker.chunker import chunk_text
from lumina_core.config import SHORT_BOOK_MAX_CHARS


def test_short_book_single_segment():
    text = "短" * (SHORT_BOOK_MAX_CHARS - 100)
    segments = chunk_text(text)
    assert len(segments) == 1
    assert segments[0].start_offset == 0


def test_long_text_multiple_segments():
    text = "第一章 开篇\n\n" + ("段落内容。" * 2000 + "\n\n") * 30
    assert len(chunk_text(text)) >= 2


def test_segments_no_overlap():
    text = "第一章 开篇\n\n" + ("段落内容。" * 1500 + "\n\n") * 40
    segments = chunk_text(text)
    for i in range(len(segments) - 1):
        assert segments[i].end_offset <= segments[i + 1].start_offset


def test_chapter_boundary_detected():
    text = "第一章 学而\n\n" + ("内容段落。" * 3000)
    assert any(s.chapter for s in chunk_text(text))
