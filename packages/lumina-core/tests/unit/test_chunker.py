"""Chunker unit tests."""

from lumina_core.chunker.chunker import chunk_text
from lumina_core.config import (
    CHUNK_MAX_CHARS,
    OLLAMA_CHUNK_MAX,
    OLLAMA_CHUNK_TARGET,
    OPENROUTER_CHUNK_MAX,
    OPENROUTER_CHUNK_TARGET,
    SHORT_BOOK_MAX_CHARS,
    ChunkBudget,
)


def test_short_book_within_hard_max_stays_single_segment():
    text = "短" * (CHUNK_MAX_CHARS - 100)
    segments = chunk_text(text)
    assert len(segments) == 1
    assert segments[0].start_offset == 0


def test_8000_char_short_book_respects_model_hard_max():
    text = "扬州城中旧事。百姓奔走相告。" * 500
    assert len(text) < SHORT_BOOK_MAX_CHARS

    budget = ChunkBudget(target_chars=2500, max_chars=3000, min_chars=1500)
    segments = chunk_text(text, budget=budget)

    assert len(segments) >= 3
    assert all(len(segment.raw_text) <= budget.max_chars for segment in segments)
    assert "".join(segment.raw_text for segment in segments) == text


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


def test_epub_toc_markers_do_not_create_tiny_segments():
    toc = "\n\n".join(
        f"## [§目录第{i}项]\n第{i}章" for i in range(160)
    )
    body = "\n\n## [§正文]\n" + ("这是正文内容，不应被目录拆成十几个字的小段。" * 500)
    text = toc + body
    budget = ChunkBudget(target_chars=2000, max_chars=2400, min_chars=1200)

    segments = chunk_text(text, budget=budget)

    assert len(segments) > 1
    assert min(len(segment.raw_text) for segment in segments[:-1]) >= budget.min_chars
    assert min(len(segment.raw_text) for segment in segments) >= 1000
    assert "".join(segment.raw_text for segment in segments) == text


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


def test_does_not_cut_inside_sentence_when_period_is_past_target():
    first = ("山" * 849) + "。"
    rest = ("随后情节继续展开并补足人物地点与事件的完整背景" * 30) + "。"
    text = first + rest
    budget = ChunkBudget(target_chars=700, max_chars=900, min_chars=500)
    segments = chunk_text(text, budget=budget)
    assert "".join(segment.raw_text for segment in segments) == text
    assert len(segments) >= 2
    assert first in segments[0].raw_text
    for segment in segments[:-1]:
        assert segment.raw_text.rstrip().endswith("。")


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


def test_ollama_budget_defaults():
    """Ollama chunk budget: target 2500, max 3000 (60%–120% 浮动)."""
    assert OLLAMA_CHUNK_TARGET == 2500
    assert OLLAMA_CHUNK_MAX == 3000


def test_ollama_budget_more_segments_than_cloud():
    text = "第一章 开篇\n\n" + ("段落内容。" * 1500 + "\n\n") * 40
    ollama = ChunkBudget(
        target_chars=OLLAMA_CHUNK_TARGET,
        max_chars=OLLAMA_CHUNK_MAX,
        min_chars=int(OLLAMA_CHUNK_TARGET * 0.6),
    )
    cloud = ChunkBudget(target_chars=4000, max_chars=4800, min_chars=2400)
    ollama_count = len(chunk_text(text, budget=ollama))
    cloud_count = len(chunk_text(text, budget=cloud))
    assert ollama_count > cloud_count


def test_openrouter_budget_fewer_segments_than_ollama():
    text = "第一章 开篇\n\n" + ("段落内容。" * 1500 + "\n\n") * 40
    ollama = ChunkBudget(
        target_chars=OLLAMA_CHUNK_TARGET,
        max_chars=OLLAMA_CHUNK_MAX,
        min_chars=int(OLLAMA_CHUNK_TARGET * 0.6),
    )
    openrouter = ChunkBudget(
        target_chars=OPENROUTER_CHUNK_TARGET,
        max_chars=OPENROUTER_CHUNK_MAX,
        min_chars=int(OPENROUTER_CHUNK_TARGET * 0.6),
    )
    ollama_count = len(chunk_text(text, budget=ollama))
    openrouter_count = len(chunk_text(text, budget=openrouter))
    assert ollama_count > openrouter_count
