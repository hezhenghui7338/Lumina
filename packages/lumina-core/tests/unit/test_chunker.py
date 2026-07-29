"""Chunker unit tests."""

from lumina_core.chunker.chunker import chunk_text
from lumina_core.config import (
    CHUNK_MAX_CHARS,
    OLLAMA_CHUNK_MAX,
    OLLAMA_CHUNK_TARGET,
    SHORT_BOOK_MAX_CHARS,
    ChunkBudget,
)


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


def test_segments_full_coverage_no_gaps():
    text = "第一章 开篇\n\n" + ("段落内容。" * 1500 + "\n\n") * 40
    stripped = text.strip()
    segments = chunk_text(text)
    assert segments[0].start_offset == 0
    assert segments[-1].end_offset == len(stripped)
    for i in range(len(segments) - 1):
        assert segments[i].end_offset == segments[i + 1].start_offset
    joined = "".join(s.raw_text for s in segments)
    assert joined == stripped


def test_chapter_boundary_detected():
    text = "第一章 学而\n\n" + ("内容段落。" * 3000)
    assert any(s.chapter for s in chunk_text(text))


def test_structure_marker_epub():
    text = "## [§第一章 缘起]\n\n" + ("这是第一章的内容。" * 800) + "\n\n## [§第二章 入京]\n\n" + ("第二章继续。" * 800)
    segments = chunk_text(text)
    assert len(segments) >= 2
    assert any(s.chapter and "§第一章" in s.chapter for s in segments)
    joined = "".join(s.raw_text for s in segments)
    assert joined == text


def test_structure_marker_pdf():
    text = "## [p.1]\n\n" + ("第一页内容。" * 500) + "\n\n## [p.2 无文本]\n\n## [p.3]\n\n" + ("第三页内容。" * 500)
    segments = chunk_text(text)
    joined = "".join(s.raw_text for s in segments)
    assert joined == text
    assert any(s.page_range for s in segments)


def test_sentence_boundary_without_paragraphs():
    """Continuous prose without newlines should split at sentence endings."""
    sentence = "这是没有换行的连续句子内容。"
    text = sentence * 900  # ~12600 chars
    segments = chunk_text(text)
    assert len(segments) >= 2
    for seg in segments[:-1]:
        assert seg.raw_text.endswith("。") or seg.raw_text.endswith("！") or seg.raw_text.endswith("？")
    joined = "".join(s.raw_text for s in segments)
    assert joined == text


def test_segments_within_max_chars():
    text = "第一章 开篇\n\n" + ("段落内容。" * 1500 + "\n\n") * 40
    segments = chunk_text(text)
    for seg in segments:
        assert len(seg.raw_text) <= CHUNK_MAX_CHARS


def test_ollama_budget_segments_within_max_chars():
    text = "第一章 开篇\n\n" + ("段落内容。" * 1500 + "\n\n") * 40
    budget = ChunkBudget(
        target_chars=OLLAMA_CHUNK_TARGET,
        max_chars=OLLAMA_CHUNK_MAX,
        min_chars=int(OLLAMA_CHUNK_TARGET * 0.6),
    )
    segments = chunk_text(text, budget=budget)
    assert len(segments) >= 2
    for seg in segments:
        assert len(seg.raw_text) <= OLLAMA_CHUNK_MAX


def test_ollama_budget_fewer_segments_than_legacy():
    text = "第一章 开篇\n\n" + ("段落内容。" * 1500 + "\n\n") * 40
    legacy = ChunkBudget(target_chars=1000, max_chars=1200, min_chars=600)
    current = ChunkBudget(
        target_chars=OLLAMA_CHUNK_TARGET,
        max_chars=OLLAMA_CHUNK_MAX,
        min_chars=int(OLLAMA_CHUNK_TARGET * 0.6),
    )
    legacy_count = len(chunk_text(text, budget=legacy))
    current_count = len(chunk_text(text, budget=current))
    assert current_count < legacy_count
