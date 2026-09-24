"""Structure tree nesting and chapter paths."""

from lumina_core.chunker.tree import (
    build_document_tree,
    chapter_path_at,
    decode_heading_path,
    heading_path_at,
    heading_path_from_chapter,
)


def test_document_tree_nests_part_chapter_section():
    text = "# [§第一卷]\n\n## [§第一章]\n\n### [§一]\n\n正文继续。"
    tree = build_document_tree(text)
    assert tree.children[0].kind == "part"
    assert tree.children[0].title == "第一卷"
    chapter = tree.children[0].children[0]
    assert chapter.kind == "chapter"
    assert chapter.title == "第一章"
    assert chapter.children[0].kind == "section"
    assert chapter.children[0].title == "一"
    body_offset = text.index("正文")
    assert chapter_path_at(tree, body_offset) == "第一卷 · 第一章 · 一"
    assert heading_path_at(tree, body_offset) == ["第一卷", "第一章", "一"]


def test_volume_hash_markers_keep_later_chapters_under_volume():
    """人性论-style: ## 卷 then ### 章 / ## 后续章 must stay under the volume."""
    from lumina_core.chunker.tree import compress_outline_path

    text = """## [§第一卷 知性]

### [§第一章 观念的起源、组合、抽象、联系等]

#### [§第一节 人类观念的起源]

正文甲。

## [§第二章 空间观念和时间观念]

#### [§第一节 空间观念和时间观念的无限不可分性]

正文乙。

## [§第二卷 情感]

### [§第一章 骄傲与谦卑]

#### [§第一节 对象和原因的划分]

正文丙。
"""
    tree = build_document_tree(text)
    roots = [child.title for child in tree.children]
    assert roots == ["第一卷 知性", "第二卷 情感"]
    vol1 = tree.children[0]
    assert [c.title for c in vol1.children] == [
        "第一章 观念的起源、组合、抽象、联系等",
        "第二章 空间观念和时间观念",
    ]

    path_a = heading_path_at(tree, text.index("正文甲"))
    path_b = heading_path_at(tree, text.index("正文乙"))
    path_c = heading_path_at(tree, text.index("正文丙"))
    assert path_a[0] == "第一卷 知性"
    assert path_b[0] == "第一卷 知性"
    assert "第二章 空间观念和时间观念" in path_b
    assert path_c[0] == "第二卷 情感"

    assert compress_outline_path(path_a)[0] == [
        "第一卷 知性",
        "第一章 观念的起源、组合、抽象、联系等",
    ]
    assert compress_outline_path(path_b)[0] == [
        "第一卷 知性",
        "第二章 空间观念和时间观念",
    ]
    assert compress_outline_path(path_c)[0] == ["第二卷 情感", "第一章 骄傲与谦卑"]


def test_nest_flat_outline_paths_infers_volume_chapter():
    from lumina_core.chunker.tree import nest_flat_outline_paths

    flat = [
        ("第一卷 知性",),
        ("第一章 观念的起源",),
        ("第一节 人类观念的起源",),
        ("第二章 空间观念",),
        ("第二卷 情感",),
        ("第一章 骄傲与谦卑",),
    ]
    nested = nest_flat_outline_paths(flat)
    assert nested[0] == ("第一卷 知性",)
    assert nested[1] == ("第一卷 知性", "第一章 观念的起源")
    assert nested[2] == ("第一卷 知性", "第一章 观念的起源", "第一节 人类观念的起源")
    assert nested[3] == ("第一卷 知性", "第二章 空间观念")
    assert nested[4] == ("第二卷 情感",)
    assert nested[5] == ("第二卷 情感", "第一章 骄傲与谦卑")


def test_chapter_path_falls_back_to_section_when_no_chapter():
    text = "### [§导言]\n\n没有章标记的小节。"
    tree = build_document_tree(text)
    offset = text.index("没有")
    assert chapter_path_at(tree, offset) == "导言"
    assert heading_path_at(tree, offset) == ["导言"]


def test_heading_path_preface_is_single_level():
    text = "## [§序言]\n\n" + ("序言正文。" * 40)
    tree = build_document_tree(text)
    offset = text.index("序言正文")
    assert heading_path_at(tree, offset) == ["序言"]


def test_heading_path_includes_section():
    text = "# [§第一部分]\n\n## [§第一章]\n\n### [§第一节]\n\n章内小节。"
    tree = build_document_tree(text)
    assert heading_path_at(tree, text.index("章内")) == ["第一部分", "第一章", "第一节"]


def test_heading_path_from_legacy_chapter_label():
    assert heading_path_from_chapter("§第一卷 · 第一章") == ["第一卷", "第一章"]
    assert heading_path_from_chapter("§合集 · 年份 · 文章") == ["合集", "年份", "文章"]
    assert heading_path_from_chapter("§序言") == ["序言"]
    assert heading_path_from_chapter("§§第一章") == ["第一章"]
    assert heading_path_from_chapter(None) == []
    assert heading_path_from_chapter("  ") == []


def test_decode_heading_path_falls_back_to_chapter():
    assert decode_heading_path(None, chapter="§第一卷 · 第一章") == ["第一卷", "第一章"]
    assert decode_heading_path(None, chapter="§合集 · 年份 · 文章") == [
        "合集",
        "年份",
        "文章",
    ]
    assert decode_heading_path('["第一部分", "第二章"]') == ["第一部分", "第二章"]
    assert decode_heading_path('["合集", "年份", "文章"]') == ["合集", "年份", "文章"]
    assert decode_heading_path([" 第一部分 ", ""], chapter="§其它") == ["第一部分"]
    assert decode_heading_path('["§§第一章"]') == ["第一章"]


def test_source_section_sign_stripped_from_tree_title():
    text = "## [§§第一章]\n\n正文继续。"
    tree = build_document_tree(text)
    assert [node.title for node in tree.children] == ["第一章"]
    assert chapter_path_at(tree, text.index("正文")) == "第一章"
    assert heading_path_at(tree, text.index("正文")) == ["第一章"]
    assert "§" not in (chapter_path_at(tree, text.index("正文")) or "")


def test_decorated_chapter_title_has_clean_path():
    text = (
        "前文收束。\n"
        "　　（第三回完）\n"
        "　　木婉清缓缓拉开了面幕。\n"
        "　　————————————第四章崖高人远\n"
        "　　奔出数里，黑玫瑰走上了一条长岭。"
    )
    tree = build_document_tree(text)
    assert [node.title for node in tree.children] == ["第四章崖高人远"]
    assert chapter_path_at(tree, text.index("拉开了面幕")) is None
    assert chapter_path_at(tree, text.index("奔出数里")) == "第四章崖高人远"
    assert heading_path_at(tree, text.index("奔出数里")) == ["第四章崖高人远"]
