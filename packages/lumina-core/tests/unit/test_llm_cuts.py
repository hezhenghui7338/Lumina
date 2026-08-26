"""Advanced-tier LLM cut snapping."""

from lumina_core.chunker.llm_cuts import _apply_relative_cuts, needs_llm_cut


def test_needs_llm_cut_skips_punctuated_paragraphs():
    chunk = "第一句完整。\n\n第二句也完整。" * 80
    assert needs_llm_cut(chunk, max_chars=len(chunk) + 10) is False


def test_needs_llm_cut_flags_unpunctuated_oversize():
    chunk = "甲" * 900
    assert needs_llm_cut(chunk, max_chars=1000) is True


def test_relative_cuts_snap_to_sentence_end():
    first = "甲段完整句子。"
    middle = "乙" * 40
    rest = "。丙段结尾。"
    text = first + middle + rest
    spans = _apply_relative_cuts(
        text,
        0,
        len(text),
        [len(first) + 10],
        max_chars=len(text),
        min_chars=1,
    )
    assert spans[0] == (0, len(first))
    assert "".join(text[start:end] for start, end in spans) == text
