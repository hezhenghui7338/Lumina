"""Ingest heading / page marker helpers."""

from lumina_core.chunker.markers import (
    clean_structure_title,
    heading_marker,
    is_hard_heading_line,
    is_hash_heading_line,
    is_page_line,
    lumina_chapter_label,
    match_bare_chapter,
    parse_heading_line,
)


def test_heading_marker_levels():
    assert heading_marker("第一卷", 0) == "# [§第一卷]"
    assert heading_marker("第一章", 1) == "## [§第一章]"
    assert heading_marker("第一节", 2) == "### [§第一节]"
    assert heading_marker("小节", 5) == "###### [§小节]"


def test_heading_marker_strips_source_section_sign():
    assert heading_marker("§ 第一章", 1) == "## [§第一章]"
    assert heading_marker("§§ 1. Intro", 1) == "## [§1. Intro]"
    assert heading_marker("卷一 §", 0) == "# [§卷一]"
    assert clean_structure_title("A § B") == "A § B"
    assert lumina_chapter_label("§§第一章") == "§第一章"
    assert lumina_chapter_label("§ 第一章") == "§第一章"
    assert lumina_chapter_label("第一章") == "§第一章"
    assert lumina_chapter_label("§") is None
    assert parse_heading_line("## [§§第一章]") == (1, "第一章")
    assert parse_heading_line("# § 第一卷") == (0, "第一卷")


def test_page_line_is_not_a_hard_heading():
    assert is_page_line("## [p.3]")
    assert not is_hard_heading_line("## [p.3]")
    assert is_hard_heading_line("## [§第一章]")
    assert is_hard_heading_line("第一章 学而")
    assert is_hard_heading_line("第七章初始")
    assert is_hard_heading_line("第七章重阳遗刻")
    assert is_hard_heading_line("第七章　重阳遗刻")
    assert not is_hard_heading_line("### [§第一节]")
    assert not is_hard_heading_line("第一节补充人物来历与场景细节。" * 8)
    assert not is_hard_heading_line("第一章只有很短的内容。" * 8)
    assert is_hash_heading_line("## [§正文]")
    assert is_hash_heading_line("# 目录")
    assert not is_hash_heading_line("第0章")
    assert not is_hash_heading_line("## [p.3]")


def test_decorated_chapter_title_is_hard_heading():
    assert is_hard_heading_line("————————————第四章崖高人远")
    assert parse_heading_line("————————————第四章崖高人远") == (1, "第四章崖高人远")
    assert is_hard_heading_line("── 第四章 崖高人远 ──")
    assert parse_heading_line("── 第四章 崖高人远 ──") == (1, "第四章 崖高人远")
    assert is_hard_heading_line("第一章·缘起")
    assert parse_heading_line("第一章·缘起") == (1, "第一章·缘起")
    assert not is_hard_heading_line("（第三回完）")
    assert parse_heading_line("（第三回完）") is None
    assert not is_hard_heading_line("段誉道：“这是第四章的事吗？”")


def test_match_bare_chapter_rejects_huge_line_quickly():
    import time

    huge = "甲" * 250_000
    started = time.monotonic()
    assert match_bare_chapter(huge) is None
    assert time.monotonic() - started < 0.2
    dashed = ("—" * 80_000) + "后文继续。"
    started = time.monotonic()
    assert match_bare_chapter(dashed) is None
    assert time.monotonic() - started < 0.2


def test_match_bare_chapter_rejects_separator_line_quickly():
    """≤120-char `====` / `----` must not enter nested-decor ReDoS (仙逆 ~88%)."""
    import time

    from lumina_core.chunker.markers import (
        BARE_CHAPTER,
        match_structure_line,
        may_be_chapter_line,
    )

    for line in ("=" * 62, "-" * 80, "=" * 120, "—" * 50, "- " * 40):
        started = time.monotonic()
        assert not may_be_chapter_line(line)
        assert match_bare_chapter(line) is None
        assert match_structure_line(line) is None
        assert BARE_CHAPTER.match(line) is None
        assert time.monotonic() - started < 0.05, (line[:20], time.monotonic() - started)


def test_match_bare_chapter_keeps_decorated_titles():
    match = match_bare_chapter("————————————第四章崖高人远")
    assert match is not None
    from lumina_core.chunker.markers import bare_chapter_title

    assert bare_chapter_title(match) == "第四章崖高人远"
    assert match_bare_chapter("── 第四章 崖高人远 ──") is not None
    assert match_bare_chapter("第一章 开篇") is not None
    assert match_bare_chapter("第一章·缘起") is not None
