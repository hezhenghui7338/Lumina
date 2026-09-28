"""In-place outline rebuild from TOC / year nesting heuristic."""

from __future__ import annotations

import json

from lumina_core.chunker.tree import decode_heading_path
from lumina_core.db.schema import init_db
from lumina_core.jobs.outline_rebuild import (
    assign_paths_from_toc,
    is_year_title,
    nest_year_paths_heuristic,
    rebuild_outline_for_book,
    segment_path_hints,
    titles_from_raw_tip,
)


def test_is_year_title_zeng_style():
    assert is_year_title("咸丰元年")
    assert is_year_title("同治十一年")
    assert not is_year_title("致诸弟")
    assert not is_year_title("家书")


def test_titles_from_raw_tip_reads_leading_markers():
    raw = "# [§家书]\n## [§咸丰元年]\n### [§致诸弟]\n正文开始。"
    assert titles_from_raw_tip(raw) == ["家书", "咸丰元年", "致诸弟"]


def test_assign_paths_from_toc_keeps_collection_year_article():
    toc = [
        ("家书",),
        ("家书", "咸丰元年"),
        ("家书", "咸丰元年", "致诸弟"),
        ("家书", "咸丰元年", "再致诸弟"),
        ("家书", "咸丰二年", "复胡林翼"),
    ]
    hints = [
        ["家书"],
        ["咸丰元年"],
        ["致诸弟"],
        ["致诸弟"],
        ["再致诸弟"],
        ["复胡林翼"],
    ]
    assigned = assign_paths_from_toc(hints, toc)
    assert assigned[0] == ("家书",)
    assert assigned[1] == ("家书", "咸丰元年")
    assert assigned[2] == ("家书", "咸丰元年", "致诸弟")
    assert assigned[3] == ("家书", "咸丰元年", "致诸弟")
    assert assigned[4] == ("家书", "咸丰元年", "再致诸弟")
    assert assigned[5] == ("家书", "咸丰二年", "复胡林翼")


def test_nest_year_paths_heuristic_fixes_siblings():
    broken = [
        ["家书"],
        ["咸丰元年"],
        ["致诸弟"],
        ["咸丰二年"],
        ["复胡林翼"],
    ]
    assert nest_year_paths_heuristic(broken) == [
        ["家书"],
        ["家书", "咸丰元年"],
        ["家书", "咸丰元年", "致诸弟"],
        ["家书", "咸丰二年"],
        ["家书", "咸丰二年", "复胡林翼"],
    ]


def test_rebuild_outline_for_book_updates_heading_path_only(tmp_path):
    conn = init_db(tmp_path / "t.db")
    book_id = "b1"
    conn.execute(
        """
        INSERT INTO books (id, title, author, format, file_path, segment_count, status, created_at, updated_at)
        VALUES (?, '曾国藩全集', '', 'epub', ?, 3, 'reading', datetime('now'), datetime('now'))
        """,
        (book_id, str(tmp_path / "missing.epub")),
    )
    rows = [
        ("s0", 0, "§家书", json.dumps(["家书"], ensure_ascii=False), "# [§家书]\n序"),
        ("s1", 1, "§咸丰元年", json.dumps(["咸丰元年"], ensure_ascii=False), "# [§咸丰元年]\n年"),
        (
            "s2",
            2,
            "§致诸弟",
            json.dumps(["致诸弟"], ensure_ascii=False),
            "## [§致诸弟]\n短文",
        ),
    ]
    conn.executemany(
        """
        INSERT INTO segments (
          id, book_id, idx, chapter, heading_path, raw_text, char_count, summary_status, retry_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'ready', 0)
        """,
        [
            (sid, book_id, idx, chapter, hp, raw, len(raw))
            for sid, idx, chapter, hp, raw in rows
        ],
    )
    conn.commit()

    result = rebuild_outline_for_book(conn, book_id, use_heuristic=True)
    assert result.updated == 2
    assert result.mode == "heuristic"

    paths = [
        decode_heading_path(row["heading_path"], chapter=row["chapter"])
        for row in conn.execute(
            "SELECT chapter, heading_path FROM segments WHERE book_id = ? ORDER BY idx",
            (book_id,),
        )
    ]
    assert paths == [
        ["家书"],
        ["家书", "咸丰元年"],
        ["家书", "咸丰元年"],
    ]
    labels = [
        row["label"]
        for row in conn.execute(
            "SELECT label FROM segments WHERE book_id = ? ORDER BY idx",
            (book_id,),
        )
    ]
    assert labels[2] == "致诸弟"
    # Summaries untouched (none written); raw_text unchanged.
    raws = [
        row["raw_text"]
        for row in conn.execute(
            "SELECT raw_text FROM segments WHERE book_id = ? ORDER BY idx", (book_id,)
        )
    ]
    assert raws[2].startswith("## [§致诸弟]")


def test_segment_path_hints_prefer_markers():
    hints = segment_path_hints(
        heading_path=["错"],
        chapter="§其它",
        raw_tip="# [§家书]\n## [§咸丰元年]\n正文",
    )
    assert hints == ["家书", "咸丰元年"]


def test_normalize_outline_title_fuzzy_match():
    from lumina_core.jobs.outline_rebuild import normalize_outline_title

    assert normalize_outline_title("001．迭奉谕旨缕陈各路军情折　正月初九日") == (
        normalize_outline_title("001. 迭奉谕旨缕陈各路军情折 正月初九日")
    )
    assert normalize_outline_title("折[3]二月二十日") == normalize_outline_title(
        "折二月二十日"
    )


def test_assign_paths_from_toc_fuzzy_and_volume_sticky():
    toc = [
        ("曾国藩全集1",),
        ("曾国藩全集1", "道光三十年"),
        ("曾国藩全集1", "道光三十年", "002．遵议大礼疏正月二十八日"),
        ("曾国藩全集1", "道光三十年", "003．应诏陈言疏三月初二日"),
        ("曾国藩全集2",),
        ("曾国藩全集2", "咸丰六年", "001．迭奉谕旨缕陈各路军情折正月初九日"),
    ]
    hints = [
        ["曾国藩全集1"],
        ["002. 遵议大礼疏正月二十八日"],
        ["003. 应诏陈言疏三月初二日"],
        ["曾国藩全集2"],
        ["001．迭奉谕旨缕陈各路军情折正月初九日"],
    ]
    assigned = assign_paths_from_toc(hints, toc)
    assert assigned[0] == ("曾国藩全集1",)
    # TOC match keeps full path; compress_outline_path runs at persist/rebuild write.
    assert assigned[1] == (
        "曾国藩全集1",
        "道光三十年",
        "002．遵议大礼疏正月二十八日",
    )
    assert assigned[2] == (
        "曾国藩全集1",
        "道光三十年",
        "003．应诏陈言疏三月初二日",
    )
    assert assigned[3] == ("曾国藩全集2",)
    assert assigned[4] == (
        "曾国藩全集2",
        "咸丰六年",
        "001．迭奉谕旨缕陈各路军情折正月初九日",
    )


def test_assign_paths_from_toc_month_leaf_does_not_rewind_year():
    """Diary months repeat under every year; restating the volume must not snap back."""
    toc = [
        ("曾国藩全集16",),
        ("曾国藩全集16", "道光十九年"),
        ("曾国藩全集16", "道光十九年", "十二月"),
        ("曾国藩全集16", "道光二十年"),
        ("曾国藩全集16", "道光二十年", "二月"),
        ("曾国藩全集16", "道光二十一年"),
        ("曾国藩全集16", "道光二十一年", "二月"),
        ("曾国藩全集16", "道光二十一年", "十二月"),
        ("曾国藩全集16", "道光二十二年"),
        ("曾国藩全集16", "道光二十二年", "二月"),
    ]
    hints = [
        ["曾国藩全集16"],
        ["道光二十一年"],
        # Body segment restates volume via heading_path fallback — must not reset cursor.
        ["曾国藩全集16", "道光二十一年"],
        ["二月"],  # must stay under 道光二十一年, not jump to 道光十九/二十年
        ["道光二十二年"],
        ["二月"],
    ]
    assigned = assign_paths_from_toc(hints, toc)
    assert assigned[0] == ("曾国藩全集16",)
    assert assigned[1] == ("曾国藩全集16", "道光二十一年")
    assert assigned[2] == ("曾国藩全集16", "道光二十一年")
    assert assigned[3] == ("曾国藩全集16", "道光二十一年", "二月")
    assert assigned[4] == ("曾国藩全集16", "道光二十二年")
    assert assigned[5] == ("曾国藩全集16", "道光二十二年", "二月")


def test_fill_sticky_outline_paths_inherits_body_segments():
    from lumina_core.jobs.outline_rebuild import fill_sticky_outline_paths

    assigned = [
        ("曾国藩全集1", "道光三十年", "002．遵议大礼疏正月二十八日"),
        None,
        None,
        ("曾国藩全集2", "目录"),
    ]
    hints = [
        ["曾国藩全集1", "002. 遵议大礼疏正月二十八日"],
        [],
        [],
        ["曾国藩全集2", "目录"],
    ]
    filled = fill_sticky_outline_paths(
        assigned, hints, volume_roots={"曾国藩全集1", "曾国藩全集2"}
    )
    assert filled[0] == [
        "曾国藩全集1",
        "道光三十年",
        "002．遵议大礼疏正月二十八日",
    ]
    assert filled[1] == filled[0]
    assert filled[2] == filled[0]
    assert filled[3] == ["曾国藩全集2", "目录"]


def test_compress_outline_path_caps_two_levels_and_returns_label():
    from lumina_core.chunker.tree import compress_outline_path

    path, label = compress_outline_path(
        ["曾国藩全集1", "道光三十年", "002．遵议大礼疏正月二十八日"]
    )
    assert path == ["曾国藩全集1", "道光三十年"]
    assert label and label.startswith("002")

    path, label = compress_outline_path(["家书", "咸丰元年", "致诸弟"])
    assert path == ["家书", "咸丰元年"]
    assert label == "致诸弟"

    path, label = compress_outline_path(["2.1 标题", "2.1 标题"])
    assert path == ["2.1 标题"]
    assert label is None

    path, label = compress_outline_path(
        ["第 2 章 复杂 HTML 解析", "2.2 再端一碗", "2.2.1 findAll"]
    )
    assert path == ["第 2 章 复杂 HTML 解析", "2.2 再端一碗"]
    assert label == "2.2.1 findAll"

    path, label = compress_outline_path(
        ["第一部分 创建爬虫", "第 2 章 复杂 HTML 解析", "2.2 再端一碗", "2.2.1 findAll"]
    )
    assert path == ["第一部分 创建爬虫", "第 2 章 复杂 HTML 解析"]
    assert label == "2.2 再端一碗"

    # 部分 · 章 must stay two levels (catalog / never-freeze heading_path).
    path, label = compress_outline_path(["第一部分", "第一章"])
    assert path == ["第一部分", "第一章"]
    assert label is None

    path, label = compress_outline_path(["第一部分", "第一章", "第一节"])
    assert path == ["第一部分", "第一章"]
    assert label == "第一节"

    # 第N卷（可带副题）优先于章+节，避免《人性论》等丢掉卷一级。
    path, label = compress_outline_path(
        ["第一卷 知性", "第一章 观念的起源、组合、抽象、联系等", "第一节 人类观念的起源"]
    )
    assert path == ["第一卷 知性", "第一章 观念的起源、组合、抽象、联系等"]
    assert label == "第一节 人类观念的起源"

    path, label = compress_outline_path(
        ["第二卷 情感", "第一章 骄傲与谦卑", "第一节 对象和原因的划分"]
    )
    assert path == ["第二卷 情感", "第一章 骄傲与谦卑"]
    assert label == "第一节 对象和原因的划分"


def test_nest_flat_outline_paths_infers_chapter_section():
    from lumina_core.chunker.tree import nest_flat_outline_paths

    flat = [
        ("第一部分 创建爬虫",),
        ("第 1 章 初见网络爬虫",),
        ("1.1 网络连接",),
        ("1.2 BeautifulSoup简介",),
        ("1.2.1 安装BeautifulSoup",),
        ("第 2 章 复杂 HTML 解析",),
        ("2.1 不是一直都要用锤子",),
        ("2.4 正则表达式和BeautifulSoup",),
        ("2.6 Lambda表达式",),
        ("第二部分 高级数据采集",),
        ("第 7 章 数据清洗",),
        ("7.1 编写代码清洗数据",),
    ]
    nested = nest_flat_outline_paths(flat)
    assert nested[0] == ("第一部分 创建爬虫",)
    assert nested[1] == ("第一部分 创建爬虫", "第 1 章 初见网络爬虫")
    assert nested[2] == ("第一部分 创建爬虫", "第 1 章 初见网络爬虫", "1.1 网络连接")
    assert nested[3] == (
        "第一部分 创建爬虫",
        "第 1 章 初见网络爬虫",
        "1.2 BeautifulSoup简介",
    )
    assert nested[4] == (
        "第一部分 创建爬虫",
        "第 1 章 初见网络爬虫",
        "1.2 BeautifulSoup简介",
        "1.2.1 安装BeautifulSoup",
    )
    assert nested[5] == ("第一部分 创建爬虫", "第 2 章 复杂 HTML 解析")
    assert nested[6] == (
        "第一部分 创建爬虫",
        "第 2 章 复杂 HTML 解析",
        "2.1 不是一直都要用锤子",
    )
    assert nested[7] == (
        "第一部分 创建爬虫",
        "第 2 章 复杂 HTML 解析",
        "2.4 正则表达式和BeautifulSoup",
    )
    assert nested[8] == (
        "第一部分 创建爬虫",
        "第 2 章 复杂 HTML 解析",
        "2.6 Lambda表达式",
    )
    assert nested[9] == ("第二部分 高级数据采集",)
    assert nested[10] == ("第二部分 高级数据采集", "第 7 章 数据清洗")
    assert nested[11] == (
        "第二部分 高级数据采集",
        "第 7 章 数据清洗",
        "7.1 编写代码清洗数据",
    )
    # Already nested TOC is left alone.
    assert nest_flat_outline_paths([("部", "章", "节")]) == [("部", "章", "节")]


def test_reattach_sandwiched_zeng_articles_keeps_volume_13_whole():
    """UI 段 3955–3956 (idx 3954–3955) were stored as their own roots.

    Footnote marks glued into the批牍 title, e.g. 「由(8)五月十六早」, so the
    path was only the article. That sat beside 曾国藩全集13 and split the volume.
    """
    from lumina_core.jobs.outline_rebuild import reattach_sandwiched_zeng_articles

    year = ["曾国藩全集13", "咸丰十一年"]
    article_0402 = ["0402．批唐镇军义训禀报近日进止机宜由(8)五月十六早"]
    article_0406 = ["0406．批朱镇军品隆禀陈近日击剿机宜由(12)五月二十二日辰正"]
    paths = [
        ["曾国藩全集13", "咸丰十年"],
        year,
        article_0402,
        article_0406,
        list(year),
        ["曾国藩全集14"],
        ["同治元年"],
        ["曾国藩全集14", "同治元年", "贺年"],
    ]
    fixed = reattach_sandwiched_zeng_articles(paths)
    assert fixed[1] == year
    assert fixed[2] == year
    assert fixed[3] == year
    assert fixed[4] == year
    # Only this sandwich. A real volume boundary and a lone year stay.
    assert fixed[0] == ["曾国藩全集13", "咸丰十年"]
    assert fixed[5] == ["曾国藩全集14"]
    assert fixed[6] == ["同治元年"]
    assert fixed[7] == ["曾国藩全集14", "同治元年", "贺年"]


def test_compress_zeng_outline_path_keeps_volume_year_only():
    from lumina_core.jobs.outline_rebuild import compress_zeng_outline_path

    assert compress_zeng_outline_path(
        ["曾国藩全集1", "道光三十年", "002．遵议大礼疏正月二十八日"]
    ) == ["曾国藩全集1", "道光三十年"]
    assert compress_zeng_outline_path(
        ["曾国藩全集11", "同治八年", "七月"]
    ) == ["曾国藩全集11", "同治八年"]


def test_sanitize_outline_path_with_label_caps_depth():
    from lumina_core.jobs.outline_rebuild import sanitize_outline_path_with_label

    path, label = sanitize_outline_path_with_label(
        ["曾国藩全集1", "道光三十年", "003．应诏陈言疏三月初二日"],
        volume_roots={"曾国藩全集1"},
    )
    assert path == ["曾国藩全集1", "道光三十年"]
    assert label and "应诏" in label

    path, label = sanitize_outline_path_with_label(
        ["合集", "咸丰二年", "复胡林翼"],
    )
    assert path == ["合集", "咸丰二年"]
    assert label == "复胡林翼"

def test_titles_from_raw_tip_skips_part_junk():
    raw = "# [§曾国藩全集1]\n## [§part0003]\n### [§目录]\n正文"
    assert titles_from_raw_tip(raw) == ["曾国藩全集1", "目录"]


def test_year_core_title_strips_month():
    from lumina_core.jobs.outline_rebuild import year_core_title

    assert year_core_title("咸丰十年正月") == "咸丰十年"
    assert year_core_title("同治十一年") == "同治十一年"
    assert year_core_title("七月") is None

def test_build_volume_ranges_from_markers_keeps_1_to_n_order():
    from lumina_core.jobs.outline_rebuild import build_volume_ranges_from_markers

    markers = [
        (2, 1),
        (100, 2),
        (200, 4),  # missing 3 between 2 and 4
        (300, 5),
    ]
    ranges = build_volume_ranges_from_markers(
        markers,
        segment_count=400,
        toc_weights={1: 10, 2: 10, 3: 10, 4: 10, 5: 10},
        max_volume=5,
    )
    vols = [vol for _a, _b, vol in ranges]
    assert vols == [1, 2, 3, 4, 5]
    # Volume 1 starts at 0 (before first body marker); 2 starts at its marker.
    assert ranges[0][0] == 0
    assert ranges[1][0] == 100
    assert ranges[-1][1] == 400


def test_apply_volume_reading_order_forces_prefix():
    from lumina_core.jobs.outline_rebuild import apply_volume_reading_order

    paths = [
        ["曾国藩全集20", "咸丰元年", "疏"],  # wrongly tagged early
        ["曾国藩全集2", "目录"],
        ["曾国藩全集2", "咸丰六年", "折"],
    ]
    ranges = [(0, 1, 1), (1, 3, 2)]
    fixed = apply_volume_reading_order(
        paths,
        segment_indices=[0, 1, 2],
        ranges=ranges,
        toc_paths=[
            ("曾国藩全集1", "咸丰元年", "疏"),
            ("曾国藩全集2", "目录"),
            ("曾国藩全集2", "咸丰六年", "折"),
        ],
        volume_roots={"曾国藩全集1", "曾国藩全集2", "曾国藩全集20"},
    )
    assert fixed[0][0] == "曾国藩全集1"
    assert fixed[1][0] == "曾国藩全集2"
    assert fixed[2][0] == "曾国藩全集2"


def test_build_volume_ranges_strict_uses_marker_positions_only():
    from lumina_core.jobs.outline_rebuild import build_volume_ranges_strict

    ranges = build_volume_ranges_strict(
        [(2, 1), (100, 2), (250, 13), (400, 14)],
        segment_count=500,
    )
    assert ranges[0] == (0, 100, 1)  # material before first marker → vol 1
    assert ranges[1] == (100, 250, 2)
    assert ranges[2] == (250, 400, 13)
    assert ranges[3] == (400, 500, 14)


def test_find_volume_markers_full_text_mid_segment():
    from lumina_core.jobs.outline_rebuild import find_volume_markers_full_text

    hits = find_volume_markers_full_text(
        [
            (10, "前文\n# [§曾国藩全集13]\n正文"),
            (11, "# [§曾国藩全集14]\n开篇"),
        ]
    )
    assert len(hits) == 2
    assert hits[0].volume == 13 and hits[0].at_start is False and hits[0].offset > 0
    assert hits[1].volume == 14 and hits[1].at_start is True


def test_split_segment_at_and_realign_resummarize_indices(tmp_path):
    from lumina_core.db.repos import BookRepo, SegmentRepo
    from lumina_core.jobs.outline_rebuild import realign_volume_markers_for_book

    conn = init_db(tmp_path / "split.db")
    book_id = "bz"
    BookRepo(conn).insert(
        id=book_id,
        title="曾国藩全集",
        format="epub",
        file_path=str(tmp_path / "x.epub"),
        segment_count=2,
        status="summarized",
    )
    left_raw = "卷尾残留。\n# [§曾国藩全集2]\n卷二开篇。"
    SegmentRepo(conn).insert_many(
        [
            {
                "id": "s0",
                "book_id": book_id,
                "idx": 0,
                "raw_text": "# [§曾国藩全集1]\n卷一。",
                "summary_status": "ready",
                "heading_path": ["曾国藩全集1"],
            },
            {
                "id": "s1",
                "book_id": book_id,
                "idx": 1,
                "raw_text": left_raw,
                "summary_status": "ready",
                "heading_path": ["曾国藩全集1"],
            },
        ]
    )
    offset = left_raw.index("# [§曾国藩全集2]")
    result = realign_volume_markers_for_book(conn, book_id)
    assert result.splits == 1
    assert result.resummarize_indices == [1, 2]
    segs = list(
        conn.execute(
            "SELECT idx, raw_text, summary_status FROM segments WHERE book_id=? ORDER BY idx",
            (book_id,),
        )
    )
    assert len(segs) == 3
    assert segs[1]["raw_text"].endswith("卷尾残留。\n") or segs[1]["raw_text"].startswith(
        "卷尾残留"
    )
    assert segs[2]["raw_text"].startswith("# [§曾国藩全集2]")
    assert segs[1]["summary_status"] == "pending"
    assert segs[2]["summary_status"] == "pending"
    # marker must be at start of its segment
    assert offset > 0
    conn.close()
