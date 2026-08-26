"""Structure tree nesting and chapter paths."""

from lumina_core.chunker.tree import build_document_tree, chapter_path_at


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
    assert chapter_path_at(tree, body_offset) == "第一卷 · 第一章"


def test_chapter_path_falls_back_to_section_when_no_chapter():
    text = "### [§导言]\n\n没有章标记的小节。"
    tree = build_document_tree(text)
    offset = text.index("没有")
    assert chapter_path_at(tree, offset) == "导言"


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
