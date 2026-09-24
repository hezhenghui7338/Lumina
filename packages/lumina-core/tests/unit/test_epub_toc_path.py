"""EPUB nested TOC path markers keep collection → year → article nesting."""

from __future__ import annotations

from lumina_core.chunker.chunker import ChunkBudget, chunk_text
from lumina_core.chunker.tree import build_document_tree, heading_path_at
from lumina_core.ingest.epub import (
    _NavTocParser,
    _join_heading_block,
    _path_delta_markers,
    _toc_full_path,
)


def test_nav_toc_parser_collects_full_ancestors():
    html = """
    <nav epub:type="toc">
      <ol>
        <li><a href="col.xhtml">家书</a>
          <ol>
            <li><a href="y1.xhtml">咸丰元年</a>
              <ol>
                <li><a href="a1.xhtml">致诸弟</a></li>
                <li><a href="a2.xhtml">再致诸弟</a></li>
              </ol>
            </li>
            <li><a href="y2.xhtml">咸丰二年</a>
              <ol>
                <li><a href="a3.xhtml">复胡林翼</a></li>
              </ol>
            </li>
          </ol>
        </li>
      </ol>
    </nav>
    """
    parser = _NavTocParser()
    parser.feed(html)
    parser.close()
    by_href = {href: (title, depth, ancestors) for href, title, depth, ancestors in parser.entries}
    assert by_href["col.xhtml"][2] == ()
    assert by_href["y1.xhtml"][2] == ("家书",)
    assert by_href["a1.xhtml"][2] == ("家书", "咸丰元年")
    assert by_href["a2.xhtml"][2] == ("家书", "咸丰元年")
    assert by_href["a3.xhtml"][2] == ("家书", "咸丰二年")


def test_path_delta_keeps_collection_open_across_years():
    open_path: list[str] = []
    articles = [
        ("致诸弟", ("家书", "咸丰元年")),
        ("再致诸弟", ("家书", "咸丰元年")),
        ("复胡林翼", ("家书", "咸丰二年")),
    ]
    blocks: list[str] = []
    for leaf, ancestors in articles:
        toc = (leaf, len(ancestors) + 1, ancestors)
        full_path, from_toc = _toc_full_path(toc, leaf)
        delta = _path_delta_markers(open_path, full_path, from_toc=from_toc)
        block, _ = _join_heading_block(delta, f"{leaf}正文内容。")
        blocks.append(block)
        open_path = full_path

    text = "\n\n".join(blocks)
    # Must not re-emit 家书 as a sibling-level `#` when opening 咸丰二年.
    assert text.count("# [§家书]") == 1
    assert "# [§咸丰元年]" in text or "## [§咸丰元年]" in text
    tree = build_document_tree(text)
    path = heading_path_at(tree, text.index("复胡林翼正文"))
    assert path[0] == "家书"
    assert "咸丰二年" in path
    assert path[-1] == "复胡林翼"
    # Collection and year are nested, not siblings under book.
    collection = tree.children[0]
    assert collection.title == "家书"
    year_titles = [child.title for child in collection.children]
    assert "咸丰元年" in year_titles
    assert "咸丰二年" in year_titles


def test_short_articles_do_not_merge_across_structure_headings():
    text = "\n\n".join(
        [
            "# [§家书]\n## [§咸丰元年]\n### [§致诸弟]\n短文甲。",
            "### [§再致诸弟]\n短文乙。",
            "## [§咸丰二年]\n### [§复胡林翼]\n短文丙。",
        ]
    )
    budget = ChunkBudget(target_chars=2000, max_chars=3000, min_chars=500)
    segments = chunk_text(text, budget=budget)
    paths = [list(seg.heading_path) for seg in segments]
    assert ["家书", "咸丰元年", "致诸弟"] in paths
    assert ["家书", "咸丰元年", "再致诸弟"] in paths
    assert ["家书", "咸丰二年", "复胡林翼"] in paths
    assert "".join(seg.raw_text for seg in segments) == text
