"""Adaptive semantic chunking behavior and scorer fallback."""

from __future__ import annotations

import pytest

from lumina_core.chunker.chunker import chunk_text
from lumina_core.chunker.embeddings import FallbackBoundaryScorer, RuleBoundaryScorer
from lumina_core.chunker.semantic import (
    TextStyle,
    _best_cut_offset,
    _ends_with_sentence,
    _sentence_cut_offsets,
    detect_style,
)
from lumina_core.config import ChunkBudget


class FixedScorer:
    def __init__(self, value: float) -> None:
        self.value = value

    def score_pairs(self, pairs: list[tuple[str, str]]) -> list[float]:
        return [self.value] * len(pairs)


class FailingScorer:
    def score_pairs(self, pairs: list[tuple[str, str]]) -> list[float]:
        raise RuntimeError("model unavailable")


def _assert_no_mid_sentence_cuts(segments, text: str) -> None:
    assert "".join(segment.raw_text for segment in segments) == text
    for index, segment in enumerate(segments[:-1]):
        raw = segment.raw_text
        tail = raw.rstrip(" \t")
        if tail.endswith("\n"):
            line = tail.rstrip("\n").rstrip(" \t")
            assert _ends_with_sentence(line), (
                f"segment {index} cut mid-sentence: {raw[-40:]!r}"
            )
        else:
            assert _ends_with_sentence(tail), (
                f"segment {index} cut mid-sentence: {raw[-40:]!r}"
            )


def test_short_text_still_respects_chapter_boundaries():
    first_body = "山路、松林和溪水构成了这一章的全部内容。" * 30
    second_body = "潮汐、帆船和港口开启了完全不同的一章。" * 30
    text = (
        f"第一章 山中\n\n{first_body}"
        f"\n\n第二章 海上\n\n{second_body}"
    )
    segments = chunk_text(text, max_chars=6000, scorer=FixedScorer(0.0))
    assert len(segments) >= 2
    assert segments[1].raw_text.lstrip().startswith("第二章")


def test_preface_does_not_merge_into_chapter_one():
    short_preface = "这是一段很短的卷首说明。" * 8
    main_body = "正文继续讲述人物、地点、事件及其前因后果，形成完整内容。" * 30
    text = (
        f"## [§卷首]\n\n序言\n\n{short_preface}"
        f"\n\n## [§第一章]\n\n{main_body}"
    )
    segments = chunk_text(
        text,
        budget=ChunkBudget(target_chars=600, max_chars=900, min_chars=500),
        scorer=FixedScorer(0.0),
    )

    assert len(segments) >= 2
    assert "序言" in segments[0].raw_text
    assert "正文继续讲述" not in segments[0].raw_text
    assert "正文继续讲述" in segments[1].raw_text
    assert all(
        segment.raw_text.strip() not in {"## [§卷首]", "序言", "## [§第一章]"}
        for segment in segments
    )


def test_same_role_short_heading_still_reads_until_500_chars():
    heading_body = "本章先交代地点与人物关系。" * 6
    continuation = "随后情节在同一章内继续展开，补足人物、地点与事件。" * 30
    text = (
        f"## [§第一章]\n\n{heading_body}"
        f"\n\n随后同一章的段落。\n\n{continuation}"
    )
    segments = chunk_text(
        text,
        budget=ChunkBudget(target_chars=600, max_chars=900, min_chars=500),
        scorer=FixedScorer(0.0),
    )
    assert "本章先交代地点与人物关系" in segments[0].raw_text
    assert "随后情节在同一章内继续展开" in segments[0].raw_text
    assert all(segment.raw_text.strip() != "## [§第一章]" for segment in segments)


def test_front_matter_fragments_can_merge_with_each_other():
    copyright_page = "本书版权归出版社所有，未经许可不得复制。" * 4
    dedication = "谨以此书献给默默支持我的家人。" * 4
    body = "正文从这里开始讲述完整的故事情节与人物命运。" * 30
    text = (
        f"## [§版权]\n\n{copyright_page}"
        f"\n\n## [§献词]\n\n{dedication}"
        f"\n\n## [§第一章]\n\n{body}"
    )
    segments = chunk_text(
        text,
        budget=ChunkBudget(target_chars=600, max_chars=900, min_chars=500),
        scorer=FixedScorer(0.0),
    )
    assert len(segments) >= 2
    assert "版权归出版社" in segments[0].raw_text
    assert "献给默默支持" in segments[0].raw_text
    assert "正文从这里开始" not in segments[0].raw_text
    assert "正文从这里开始" in segments[1].raw_text


def test_topic_shift_can_cut_below_min_chars():
    left = "山林生态研究记录了松树、溪流、鸟类和季节变化。" * 24
    right = "数据库事务讨论锁、日志、索引、提交与故障恢复。" * 24
    budget = ChunkBudget(target_chars=1200, max_chars=1600, min_chars=700)
    segments = chunk_text(
        f"{left}\n\n{right}",
        budget=budget,
        scorer=FixedScorer(0.95),
    )
    assert len(segments) == 2
    assert all(500 <= len(segment.raw_text) < budget.min_chars for segment in segments)


def test_coherent_short_paragraphs_are_merged():
    first = "山林观察记录了松树和溪流，也记录了鸟类迁徙。" * 5
    second = "继续观察山林中的松树、溪流与鸟类，季节已经变化。" * 5
    segments = chunk_text(
        f"{first}\n\n{second}",
        budget=ChunkBudget(target_chars=1200, max_chars=1600, min_chars=700),
        scorer=FixedScorer(0.05),
    )
    assert len(segments) == 1


def test_short_poems_merge_at_work_boundaries_until_500_chars():
    works = [
        f"诗作{i}\n山川入远目\n风月到清樽\n故人千里外\n今夜共黄昏"
        for i in range(40)
    ]
    segments = chunk_text(
        "\n\n".join(works),
        budget=ChunkBudget(target_chars=600, max_chars=900, min_chars=500),
        scorer=FixedScorer(0.0),
    )
    assert len(segments) >= 2
    assert all(len(segment.raw_text) >= 500 for segment in segments)
    assert all(segment.raw_text.lstrip().startswith("诗作") for segment in segments)


def test_classical_style_reaches_information_budget_sooner():
    classical_block = "学而时习之，不亦说乎？有朋自远方来，不亦乐乎？人不知而不愠，不亦君子乎？"
    prose_block = "今天的学习计划包括阅读、记录和复习，这些步骤会在每个阶段重复进行。"
    classical = "\n\n".join(classical_block * 3 for _ in range(20))
    prose = "\n\n".join(prose_block * 3 for _ in range(20))
    budget = ChunkBudget(target_chars=1200, max_chars=1600, min_chars=720)

    classical_segments = chunk_text(classical, budget=budget, scorer=FixedScorer(0.0))
    prose_segments = chunk_text(prose, budget=budget, scorer=FixedScorer(0.0))

    assert detect_style(classical_block * 3) is TextStyle.CLASSICAL
    assert len(classical_segments) > len(prose_segments)


def test_final_tail_is_rebalanced_to_500_chars():
    paragraphs = [
        f"第{i}部分围绕同一主题展开，并补充人物、地点、事件和详细背景。" * 8
        for i in range(7)
    ]
    segments = chunk_text(
        "\n\n".join(paragraphs),
        budget=ChunkBudget(target_chars=700, max_chars=900, min_chars=500),
        scorer=FixedScorer(0.0),
    )
    assert all(500 <= len(segment.raw_text) <= 900 for segment in segments)


def test_best_cut_offset_uses_period_between_preferred_and_max():
    first = ("山" * 849) + "。"
    # Next period must sit past max_chars so the only legal cut in-window is 850.
    rest = ("随后继续讲述人物地点与事件的完整背景" * 20) + "。"
    text = first + rest
    cut = _best_cut_offset(
        text, 0, preferred_chars=700, max_chars=900, end=len(text)
    )
    assert cut == len(first)
    assert text[:cut].endswith("。")
    assert cut < 900


def test_does_not_cut_mid_sentence_when_period_is_between_preferred_and_max():
    first = ("山" * 849) + "。"
    rest = ("随后情节继续展开并补足人物地点与事件的完整背景" * 30) + "。"
    text = first + rest
    segments = chunk_text(
        text,
        budget=ChunkBudget(target_chars=700, max_chars=900, min_chars=500),
        scorer=FixedScorer(0.0),
    )
    _assert_no_mid_sentence_cuts(segments, text)
    assert len(segments) >= 2
    assert segments[0].raw_text.startswith(first)


def test_single_newline_paragraphs_cut_at_line_not_mid_sentence():
    para_a = "甲段描述地点人物与事件背景。" * 40
    para_b = "乙段描述完全不同的后续发展过程。" * 40
    text = f"{para_a}\n{para_b}"
    segments = chunk_text(
        text,
        budget=ChunkBudget(target_chars=700, max_chars=900, min_chars=500),
        scorer=FixedScorer(0.0),
    )
    _assert_no_mid_sentence_cuts(segments, text)
    assert len(segments) >= 2
    assert segments[0].raw_text.rstrip("\n") == para_a
    assert segments[1].raw_text.lstrip("\n").startswith("乙段描述")


def test_latin_decimal_is_not_a_sentence_end():
    text = "Value is 3.14 today."
    offsets = _sentence_cut_offsets(text, 0, len(text))
    decimal_at = text.index(".")
    assert decimal_at + 1 not in offsets
    assert offsets[-1] == len(text)


@pytest.mark.parametrize("length", [499, 500, 999, 1000, 1801, 6200])
def test_global_500_char_floor_for_unstructured_text(length: int):
    segments = chunk_text(
        "文" * length,
        budget=ChunkBudget(target_chars=700, max_chars=1000, min_chars=500),
        scorer=FixedScorer(0.0),
    )
    assert "".join(segment.raw_text for segment in segments) == "文" * length
    assert all(len(segment.raw_text) <= 1000 for segment in segments)
    if length >= 500:
        assert all(len(segment.raw_text) >= 500 for segment in segments)


def test_scorer_chain_falls_back_after_failure():
    scorer = FallbackBoundaryScorer([FailingScorer(), FixedScorer(0.25)])
    assert scorer.score_pairs([("甲", "乙")]) == [0.25]
    assert scorer.selected == "FixedScorer"


def test_scorer_chain_propagates_cancellation():
    scorer = FallbackBoundaryScorer(
        [FixedScorer(0.25)],
        cancelled=lambda: True,
    )
    with pytest.raises(InterruptedError):
        scorer.score_pairs([("甲", "乙")])


def test_rule_scorer_distinguishes_repeated_and_unrelated_topics():
    scorer = RuleBoundaryScorer()
    related, unrelated = scorer.score_pairs(
        [
            ("山林中有松树溪流和飞鸟", "继续观察山林里的松树与飞鸟"),
            ("山林中有松树溪流和飞鸟", "数据库事务使用日志索引和锁"),
        ]
    )
    assert related < unrelated

def test_structure_role_hints_keep_preface_out_of_bodymatter():
    preface = "这是独立的序言，说明写作缘起。" * 4
    body = "正文从这里开始讲述完整的故事情节与人物命运。" * 30
    text = (
        f"## [§序]\n\n{preface}"
        f"\n\n## [§第一章]\n\n{body}"
    )
    segments = chunk_text(
        text,
        budget=ChunkBudget(target_chars=600, max_chars=900, min_chars=500),
        scorer=FixedScorer(0.0),
        structure_roles=[
            {"title": "序", "role": "preface"},
            {"title": "第一章", "role": "bodymatter"},
        ],
    )
    assert len(segments) >= 2
    assert "独立的序言" in segments[0].raw_text
    assert "正文从这里开始" not in segments[0].raw_text

