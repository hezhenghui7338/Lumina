"""Adaptive semantic chunking behavior and scorer fallback."""

from __future__ import annotations

import pytest

from lumina_core.chunker.chunker import chunk_text
from lumina_core.chunker.embeddings import FallbackBoundaryScorer, RuleBoundaryScorer
from lumina_core.chunker.semantic import (
    BoundaryStrength,
    TextStyle,
    _best_cut_offset,
    _ends_with_sentence,
    _paragraph_cut_offsets,
    _sentence_cut_offsets,
    atomize_text,
    detect_style,
)
from lumina_core.config import ChunkBudget, resolve_chunk_budget


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


def test_coherent_prose_does_not_cut_at_target_without_topic_shift():
    block = "山林观察记录了松树和溪流，也记录了鸟类迁徙与季节变化。" * 15
    text = f"{block}\n\n{block}"
    budget = ChunkBudget(target_chars=700, max_chars=1050, min_chars=420)
    assert budget.min_chars < len(text) <= budget.max_chars
    segments = chunk_text(text, budget=budget, scorer=FixedScorer(0.0))
    assert len(segments) == 1


def test_nested_section_markers_do_not_force_tiny_segments():
    chapter = "本章先交代地点与人物关系。" * 10
    first = "第一节补充人物来历与场景细节。" * 8
    second = "第二节继续同一章的情节发展。" * 8
    text = (
        f"## [§第一章]\n\n{chapter}\n\n"
        f"### [§第一节]\n\n{first}\n\n"
        f"### [§第二节]\n\n{second}"
    )
    budget = ChunkBudget(target_chars=600, max_chars=900, min_chars=500)
    segments = chunk_text(text, budget=budget, scorer=FixedScorer(0.0))
    assert len(segments) == 1
    assert "第一节" in segments[0].raw_text
    assert "第二节" in segments[0].raw_text


def test_page_markers_are_anchors_not_hard_cuts():
    page_one = "第一页同一章的叙述继续展开。" * 20
    page_two = "第二页仍属同一章，情节连贯。" * 20
    text = f"## [§第一章]\n\n## [p.1]\n\n{page_one}\n\n## [p.2]\n\n{page_two}"
    budget = ChunkBudget(target_chars=600, max_chars=900, min_chars=500)
    segments = chunk_text(text, budget=budget, scorer=FixedScorer(0.0))
    assert len(segments) == 1
    assert segments[0].page_range == "p.1-2"


def test_short_body_chapter_does_not_swallow_next_chapter():
    first = "第一章只有很短的内容。" * 8
    second = "第二章展开完整的人物地点与事件。" * 30
    text = f"## [§第一章]\n\n{first}\n\n## [§第二章]\n\n{second}"
    budget = ChunkBudget(target_chars=600, max_chars=900, min_chars=500)
    segments = chunk_text(text, budget=budget, scorer=FixedScorer(0.0))
    assert len(segments) >= 2
    assert "第一章只有很短" in segments[0].raw_text
    assert "第二章展开" not in segments[0].raw_text
    assert "第二章展开" in segments[1].raw_text


_PREVIOUS_CHAPTER_TAIL = (
    "这时天色已迟，太阳落到西边，天际晚霞灿烂。"
    "夕阳照在大竹峰上，这一大二小缓步向山前走去，"
    "远处峰前屋宇处，不时传来一声声长长犬吠，"
    "中间还夹杂着某些可怜人的尖声呼痛。"
)


def _long_chapter_then_heading(heading: str) -> tuple[str, ChunkBudget]:
    budget = ChunkBudget(target_chars=700, max_chars=900, min_chars=500)
    blocks = [
        f"山路松林溪水构成了这一章的全部叙述内容，并补足人物地点与事件。{i}"
        for i in range(16)
    ]
    sequel = "后续情节在全新场景中继续展开并补足人物地点。" * 24
    text = (
        "第一章 山中\n\n"
        + "\n\n".join(blocks)
        + f"\n\n{_PREVIOUS_CHAPTER_TAIL}\n{heading}\n"
        + f"　　晚饭时分，天色已暗了下来。\n\n{sequel}"
    )
    return text, budget


def _assert_heading_segment_has_no_previous_tail(
    segments,
    text: str,
    heading: str,
    tail: str,
) -> None:
    stripped = text.strip()
    assert "".join(segment.raw_text for segment in segments) == stripped
    holders = [segment for segment in segments if heading in segment.raw_text]
    assert holders
    for segment in holders:
        assert segment.raw_text.lstrip().startswith("第七章")
        assert tail not in segment.raw_text


def test_glued_chapter_title_is_hard_atom():
    text = "尾声。\n第七章初始\n　　晚饭时分，天色已暗了下来。"
    atoms = atomize_text(text, target_chars=700, max_chars=900)
    heading = next(atom for atom in atoms if "第七章初始" in atom.text)
    assert heading.boundary_before is BoundaryStrength.HARD


def test_glued_chapter_title_does_not_keep_previous_chapter_tail():
    text, budget = _long_chapter_then_heading("第七章初始")
    segments = chunk_text(text, budget=budget, scorer=FixedScorer(0.0))
    _assert_heading_segment_has_no_previous_tail(
        segments, text, "第七章初始", _PREVIOUS_CHAPTER_TAIL
    )


def test_spaced_chapter_title_after_max_pack_does_not_keep_tail():
    heading = "第七章　重阳遗刻"
    text, budget = _long_chapter_then_heading(heading)
    segments = chunk_text(text, budget=budget, scorer=FixedScorer(0.0))
    _assert_heading_segment_has_no_previous_tail(
        segments, text, heading, _PREVIOUS_CHAPTER_TAIL
    )


def test_separator_glued_chapter_title_does_not_merge_next_chapter():
    """TXT dash-prefixed 第N章 is HARD; （第N回完） is not a cut."""
    budget = ChunkBudget(target_chars=1500, max_chars=2400, min_chars=500)
    previous = "段誉心中焦急，说道：“木姑娘，你让我下马吧，你一个人容易脱身。”" * 16
    reveal = (
        "木婉清向段誉招了招手，说道：“你过来。”段誉一跛一拐的走到她身前。"
        "木婉清背脊向着南海鳄神，低声道：“你是世上第一个见到我容貌的男子！”"
        "缓缓拉开了面幕。"
    )
    heading = "————————————第四章崖高人远"
    sequel = "奔出数里，黑玫瑰走上了一条长岭，山岭渐见崎岖。" * 8
    text = (
        f"{previous}\n"
        "　　（第三回完）\n"
        "　　———————————\n"
        f"　　{reveal}\n"
        f"　　{heading}\n"
        f"　　{sequel}"
    )
    assert len(text) <= budget.max_chars
    atoms = atomize_text(text, target_chars=budget.target_chars, max_chars=budget.max_chars)
    heading_atom = next(atom for atom in atoms if heading in atom.text)
    assert heading_atom.boundary_before is BoundaryStrength.HARD
    segments = chunk_text(text, budget=budget, scorer=FixedScorer(0.0))
    reveal_holders = [segment for segment in segments if "拉开了面幕" in segment.raw_text]
    flee_holders = [segment for segment in segments if "奔出数里" in segment.raw_text]
    assert len(reveal_holders) == 1
    assert len(flee_holders) == 1
    assert reveal_holders[0] is not flee_holders[0]
    assert "奔出数里" not in reveal_holders[0].raw_text
    assert "拉开了面幕" not in flee_holders[0].raw_text
    assert "（第三回完）" in reveal_holders[0].raw_text
    assert flee_holders[0].raw_text.lstrip().startswith(heading)
    end_holders = [segment for segment in segments if "（第三回完）" in segment.raw_text]
    assert end_holders == reveal_holders


def test_bare_chapter_line_inside_toc_is_not_a_hard_cut():
    toc = "\n\n".join(f"## [§目录第{i}项]\n第{i}章" for i in range(3))
    text = toc + "\n\n## [§正文]\n" + ("正文内容。" * 40)
    atoms = atomize_text(text, target_chars=2000, max_chars=2400)
    body_start = text.find("## [§正文]")
    toc_atoms = [atom for atom in atoms if atom.start < body_start]
    assert toc_atoms
    assert toc_atoms[0].boundary_before is BoundaryStrength.HARD
    assert all(
        atom.boundary_before is BoundaryStrength.STRONG for atom in toc_atoms[1:]
    )
    body_atom = next(atom for atom in atoms if atom.start == body_start)
    assert body_atom.boundary_before is BoundaryStrength.HARD


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
    classical = "\n\n".join(classical_block * 3 for _ in range(40))
    prose = "\n\n".join(prose_block * 3 for _ in range(40))
    budget = ChunkBudget(target_chars=1200, max_chars=1600, min_chars=720)

    classical_segments = chunk_text(classical, budget=budget, scorer=FixedScorer(0.0))
    prose_segments = chunk_text(prose, budget=budget, scorer=FixedScorer(0.0))

    assert detect_style(classical_block * 3) is TextStyle.CLASSICAL
    assert len(classical_segments) > len(prose_segments)


def test_final_tail_keeps_whole_paragraphs():
    paragraphs = [
        f"第{i}部分围绕同一主题展开，并补充人物、地点、事件和详细背景。" * 8
        for i in range(7)
    ]
    text = "\n\n".join(paragraphs)
    segments = chunk_text(
        text,
        budget=ChunkBudget(target_chars=700, max_chars=900, min_chars=500),
        scorer=FixedScorer(0.0),
    )
    assert "".join(segment.raw_text for segment in segments) == text
    assert all(len(segment.raw_text) <= 900 for segment in segments)
    for paragraph in paragraphs:
        holders = [segment for segment in segments if paragraph in segment.raw_text]
        assert len(holders) == 1, paragraph[:20]


def test_best_cut_offset_prefers_paragraph_past_target_over_sentence():
    first = ("山" * 499) + "。"
    rest_of_para = ("水" * 299) + "。"
    next_para = ("林" * 200) + "。"
    text = f"{first}{rest_of_para}\n\n{next_para}"
    cut = _best_cut_offset(
        text, 0, preferred_chars=700, max_chars=900, end=len(text)
    )
    assert cut is not None
    assert cut != len(first)
    assert cut >= len(first) + len(rest_of_para)
    assert text[:cut].rstrip("\n").endswith("。")


def test_does_not_split_modest_paragraphs_across_segments():
    paragraphs = [
        f"第{i}段讲述人物地点与事件，并补充完整背景与后续发展。" * 20
        for i in range(6)
    ]
    text = "\n\n".join(paragraphs)
    segments = chunk_text(
        text,
        budget=ChunkBudget(target_chars=700, max_chars=900, min_chars=500),
        scorer=FixedScorer(0.0),
    )
    assert "".join(segment.raw_text for segment in segments) == text
    for paragraph in paragraphs:
        holders = [segment for segment in segments if paragraph in segment.raw_text]
        assert len(holders) == 1


def test_indented_single_newline_paragraphs_stay_whole():
    first = "　　" + ("甲段描述地点人物与事件背景。" * 40)
    second = "　　" + ("乙段描述完全不同的后续发展。" * 40)
    text = f"{first}\n{second}"
    segments = chunk_text(
        text,
        budget=ChunkBudget(target_chars=700, max_chars=900, min_chars=500),
        scorer=FixedScorer(0.0),
    )
    stripped = text.strip()
    assert "".join(segment.raw_text for segment in segments) == stripped
    holders_first = [segment for segment in segments if "甲段描述" in segment.raw_text]
    holders_second = [segment for segment in segments if "乙段描述" in segment.raw_text]
    assert len(holders_first) == 1
    assert len(holders_second) == 1


def test_short_trailing_paragraph_does_not_split_previous():
    first = ("甲" * 850) + "。"
    second = ("乙" * 120) + "。"
    text = f"{first}\n\n{second}"
    segments = chunk_text(
        text,
        budget=ChunkBudget(target_chars=700, max_chars=900, min_chars=500),
        scorer=FixedScorer(0.0),
    )
    assert len(segments) == 2
    assert first in segments[0].raw_text
    assert "乙" not in segments[0].raw_text
    assert second in segments[1].raw_text
    assert first not in segments[1].raw_text
    assert len(segments[1].raw_text) < 500


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


@pytest.mark.parametrize("target", [200, 400])
def test_small_target_does_not_collapse_long_prose(target: int):
    paragraphs = [
        f"第{i}段围绕人物地点与事件展开，并补充完整背景与后续发展。" * 8
        for i in range(20)
    ]
    text = "\n\n".join(paragraphs)
    budget = resolve_chunk_budget(target_chars=target)
    segments = chunk_text(text, budget=budget, scorer=FixedScorer(0.0))
    assert "".join(segment.raw_text for segment in segments) == text
    assert len(segments) >= 2
    assert all(len(segment.raw_text) <= budget.max_chars for segment in segments)
    for segment in segments[:-1]:
        assert len(segment.raw_text) >= budget.min_chars


@pytest.mark.parametrize("target", [200, 400])
def test_small_target_unstructured_text_still_splits(target: int):
    length = 2500
    budget = resolve_chunk_budget(target_chars=target)
    segments = chunk_text(
        "文" * length,
        budget=budget,
        scorer=FixedScorer(0.0),
    )
    assert "".join(segment.raw_text for segment in segments) == "文" * length
    assert len(segments) >= 2
    assert all(len(segment.raw_text) <= budget.max_chars for segment in segments)


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


def test_paragraph_cut_offsets_do_not_rescan_prefix():
    import time

    text = "这是一句完整的话。\n" * 20_000
    started = time.monotonic()
    cuts = _paragraph_cut_offsets(text, 0, len(text))
    elapsed = time.monotonic() - started
    assert elapsed < 1.5, elapsed
    assert cuts
    mid = len(text) // 2
    started = time.monotonic()
    window_cuts = _paragraph_cut_offsets(text, mid, min(len(text), mid + 8_000))
    assert time.monotonic() - started < 0.2
    assert all(mid < point <= mid + 8_000 for point in window_cuts)

