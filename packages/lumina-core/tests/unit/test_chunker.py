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
    assert any(s.heading_path and "第一章" in s.heading_path[0] for s in segments)
    joined = "".join(s.raw_text for s in segments)
    assert joined == text


def test_chapter_field_does_not_stack_section_signs():
    from lumina_core.chunker.chunker import _chapter_at

    text = "## [§§第一章]\n\n" + ("这是第一章的内容。" * 200)
    label = _chapter_at(text, text.index("这是"))
    assert label == "§第一章"
    assert "§§" not in (label or "")


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
    """Ollama chunk budget: target 2000, max 3000 (60%–150% 浮动)."""
    assert OLLAMA_CHUNK_TARGET == 2000
    assert OLLAMA_CHUNK_MAX == 3000


def test_ollama_budget_more_segments_than_cloud():
    text = "第一章 开篇\n\n" + ("段落内容。" * 1500 + "\n\n") * 40
    ollama = ChunkBudget(
        target_chars=OLLAMA_CHUNK_TARGET,
        max_chars=OLLAMA_CHUNK_MAX,
        min_chars=int(OLLAMA_CHUNK_TARGET * 0.6),
    )
    cloud = ChunkBudget(target_chars=4000, max_chars=6000, min_chars=2400)
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


def test_page_marker_scanned_once_not_per_segment(monkeypatch):
    from lumina_core.chunker import chunker as chunker_mod

    real = chunker_mod.PAGE_MARKER

    class Probe:
        def __init__(self) -> None:
            self.finditer_on_book = 0

        def finditer(self, text: str, *args, **kwargs):
            if len(text) > 80:
                self.finditer_on_book += 1
            return real.finditer(text, *args, **kwargs)

        def match(self, text: str, *args, **kwargs):
            return real.match(text, *args, **kwargs)

    probe = Probe()
    monkeypatch.setattr(chunker_mod, "PAGE_MARKER", probe)
    parts = [f"## [p.{i}]\n" + ("正文句子。" * 50) for i in range(1, 30)]
    text = "\n".join(parts)
    segments = chunk_text(text)
    assert len(segments) >= 2
    assert probe.finditer_on_book == 0


def test_chunk_text_large_txt_finishes_without_full_book_regex(monkeypatch):
    """~0.5MB line-oriented TXT must chunk in seconds, not scan BARE_CHAPTER on the book."""
    import time

    from lumina_core.chunker import markers as markers_mod
    from lumina_core.chunker.chunker import chunk_text

    real = markers_mod.BARE_CHAPTER

    class Probe:
        def finditer(self, text: str, *args, **kwargs):
            if len(text) > 400:
                raise AssertionError("BARE_CHAPTER must not finditer the whole book")
            return real.finditer(text, *args, **kwargs)

        def match(self, text: str, *args, **kwargs):
            return real.match(text, *args, **kwargs)

    monkeypatch.setattr(markers_mod, "BARE_CHAPTER", Probe())
    line = "　　这是一段用于测试超大 TXT 导入的中文句子，保证每段都有句号。\n"
    text = "第一章 开篇\n\n" + line * 4000
    started = time.monotonic()
    segments = chunk_text(text)
    elapsed = time.monotonic() - started
    assert "".join(s.raw_text for s in segments) == text.strip()
    assert elapsed < 8.0
    assert len(segments) >= 2


def test_chunk_text_releases_gil_for_other_thread():
    import threading
    import time

    ticks: list[int] = []
    stop = threading.Event()

    def ticker() -> None:
        n = 0
        while not stop.is_set():
            n += 1
            ticks.append(n)
            time.sleep(0)

    worker = threading.Thread(target=ticker)
    worker.start()
    deadline = time.monotonic() + 1.0
    while not ticks and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ticks
    before = len(ticks)
    para = "这是一段用来占用分段器的测试文字。\n\n"
    text = "第一章 开篇\n\n" + para * 2500
    chunk_text(text)
    after = len(ticks)
    stop.set()
    worker.join(timeout=2)
    assert after > before


def test_large_atom_count_uses_rule_scorer_not_embeddings(monkeypatch):
    monkeypatch.setattr("lumina_core.chunker.chunker.LARGE_ATOM_EMBED_LIMIT", 1)

    class Boom:
        def score_pairs(self, pairs):
            raise AssertionError("Ollama/ONNX must not score huge books")

    text = "第一段内容在这里。\n\n第二段内容也在这里。"
    segments = chunk_text(text, scorer=Boom())
    assert "".join(s.raw_text for s in segments) == text.strip()
