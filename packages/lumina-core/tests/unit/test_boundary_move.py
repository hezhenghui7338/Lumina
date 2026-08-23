"""Manual adjacent-segment boundary snapping and note remap."""

from __future__ import annotations

from lumina_core.chunker.boundary import (
    BoundaryError,
    apply_cut,
    list_cut_offsets,
    remap_note_segment_id,
    snap_cut_offset,
)
from lumina_core.db.repos import BookRepo, NoteRepo, SegmentRepo
from lumina_core.db.schema import init_db
import pytest


LEFT = "左侧开篇。山林里有松树与溪流。\n\n左侧续写。飞鸟停在枝头观察四季。\n\n"
RIGHT = "右侧开篇。数据库事务使用日志、索引和锁。\n\n右侧续写。并发控制保证一致性。\n\n"


def test_list_cut_offsets_includes_paragraphs_and_current():
    concat = LEFT + RIGHT
    candidates = list_cut_offsets(concat, current_offset=len(LEFT))
    offsets = [item.offset for item in candidates]
    assert 0 not in offsets
    assert len(concat) not in offsets
    assert len(LEFT) in offsets
    assert any(item.kind == "paragraph" for item in candidates)


def test_apply_cut_moves_paragraph_and_preserves_coverage():
    moved = apply_cut(LEFT, RIGHT, len(LEFT) + len("右侧开篇。数据库事务使用日志、索引和锁。\n\n"))
    assert moved.unchanged is False
    assert moved.left_text + moved.right_text == LEFT + RIGHT
    assert moved.left_text.startswith("左侧开篇")
    assert "数据库事务" in moved.left_text
    assert moved.right_text.startswith("右侧续写")


def test_apply_cut_same_offset_is_unchanged():
    moved = apply_cut(LEFT, RIGHT, len(LEFT))
    assert moved.unchanged is True
    assert moved.left_text == LEFT
    assert moved.right_text == RIGHT


def test_apply_cut_rejects_empty_side():
    with pytest.raises(BoundaryError):
        apply_cut(LEFT, RIGHT, 0)
    with pytest.raises(BoundaryError):
        apply_cut(LEFT, RIGHT, len(LEFT + RIGHT))


def test_snap_picks_nearest_candidate():
    concat = LEFT + RIGHT
    current = len(LEFT)
    snapped = snap_cut_offset(concat, current + 3, current_offset=current)
    candidates = [item.offset for item in list_cut_offsets(concat, current_offset=current)]
    assert snapped in candidates


def test_remap_note_follows_quote():
    left_id, right_id = "left", "right"
    assert (
        remap_note_segment_id("山林里有松树", left_id, left_id, right_id, LEFT, RIGHT)
        == left_id
    )
    assert (
        remap_note_segment_id("数据库事务", right_id, left_id, right_id, LEFT, "数据库事务使用日志")
        == right_id
    )
    assert (
        remap_note_segment_id("数据库事务", right_id, left_id, right_id, LEFT + "数据库事务使用日志", "并发控制")
        == left_id
    )
    assert remap_note_segment_id(None, right_id, left_id, right_id, LEFT, RIGHT) == right_id
    assert (
        remap_note_segment_id("两边都没有", left_id, left_id, right_id, LEFT, RIGHT)
        == left_id
    )


def test_segment_repo_moves_text_and_notes(tmp_path):
    conn = init_db(tmp_path / "boundary.db")
    BookRepo(conn).insert(
        id="book-b",
        title="Boundary",
        format="txt",
        file_path="/tmp/b.txt",
        segment_count=2,
        status="reading",
    )
    left = {
        "id": "seg-l",
        "book_id": "book-b",
        "idx": 0,
        "anchor_label": "〔段 1〕",
        "raw_text": LEFT,
        "char_count": len(LEFT),
        "summary_status": "ready",
        "retry_count": 0,
    }
    right = {
        "id": "seg-r",
        "book_id": "book-b",
        "idx": 1,
        "anchor_label": "〔段 2〕",
        "raw_text": RIGHT,
        "char_count": len(RIGHT),
        "summary_status": "ready",
        "retry_count": 0,
    }
    repo = SegmentRepo(conn)
    repo.insert_many([left, right])
    conn.execute(
        "UPDATE segments SET summary_json = ?, label = ?, translation = ? WHERE id = ?",
        ("{}", "左标签", "左译", "seg-l"),
    )
    conn.commit()
    notes = NoteRepo(conn)
    keep = notes.create(
        book_id="book-b",
        content="keep",
        segment_id="seg-r",
        quote="数据库事务使用日志、索引和锁。",
    )
    stay = notes.create(
        book_id="book-b",
        content="stay",
        segment_id="seg-r",
    )
    moved = apply_cut(
        LEFT,
        RIGHT,
        len(LEFT) + len("右侧开篇。数据库事务使用日志、索引和锁。\n\n"),
    )
    updated_left, updated_right = repo.apply_boundary_move(
        left,
        right,
        left_text=moved.left_text,
        right_text=moved.right_text,
        left_chapter=moved.left_chapter,
        right_chapter=moved.right_chapter,
        left_page_range=moved.left_page_range,
        right_page_range=moved.right_page_range,
        left_anchor="〔段 1〕",
        right_anchor="〔段 2〕",
        summary_tier="normal",
    )
    assert updated_left["raw_text"] + updated_right["raw_text"] == LEFT + RIGHT
    assert updated_left["summary_status"] == "pending"
    assert updated_right["summary_status"] == "pending"
    assert updated_left["summary_json"] is None
    assert updated_left["translation"] is None
    assert notes.get(keep["id"])["segment_id"] == "seg-l"
    assert notes.get(stay["id"])["segment_id"] == "seg-r"
    conn.close()
