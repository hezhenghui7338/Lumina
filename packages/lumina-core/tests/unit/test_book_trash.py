"""Trash is a visibility boundary, not a reading status or a destructive delete."""

import pytest

from lumina_core.db.repos import BOOK_FILTERS, BookIntroRepo, BookRepo, NoteRepo, SegmentRepo
from lumina_core.db.schema import init_db
from lumina_core.jobs.queue import JobQueue
from lumina_core.library_assistant import (
    LibraryPlan, apply_action, execute_plan, list_tags,
)
from lumina_core.search.fts import index_book, index_note, search
from tests.support.mock_router import MockModelRouter


@pytest.fixture
def library(tmp_path):
    conn = init_db(tmp_path / "trash.db")
    repo = BookRepo(conn)
    book = repo.insert(id="discarded", title="TRASHNEEDLE", format="txt", file_path="/x")
    SegmentRepo(conn).insert_many([{
        "id": "s1", "book_id": book["id"], "idx": 0,
        "raw_text": "Original text", "summary_status": "ready",
    }])
    SegmentRepo(conn).update_summary("s1", summary_json='{"sentences":["Saved summary"]}', label="Saved")
    repo.update(book["id"], status="reading", is_favorite=1, rating=2, category="文学",
                current_segment_index=0, last_opened_at="2026-11-13T00:00:00Z")
    book = repo.get(book["id"])
    note = NoteRepo(conn).create(book_id=book["id"], segment_id="s1", content="TRASHNEEDLE note")
    index_book(conn, book)
    index_note(conn, book, note)
    yield conn, repo, note
    conn.close()


def test_trash_filters_every_collection_and_preserves_reading_data(library):
    conn, repo, note = library
    before = repo.get("discarded")
    repo.set_trashed("discarded", True)
    trashed_at = repo.get("discarded")["trashed_at"]
    repo.set_trashed("discarded", True)
    assert repo.get("discarded")["trashed_at"] == trashed_at
    for filter_name in BOOK_FILTERS:
        assert repo.list_books(filter=filter_name) == []
    assert len(repo.list_books(visibility="trash")) == 1
    assert len(repo.list_books(visibility="all")) == 1
    assert search(conn, "TRASHNEEDLE") == []
    assert NoteRepo(conn).list_all() == []
    assert NoteRepo(conn).list_for_book("discarded")[0]["id"] == note["id"]
    assert SegmentRepo(conn).get("s1")["raw_text"] == "Original text"
    assert 'Saved summary' in SegmentRepo(conn).get("s1")["summary_json"]
    repo.set_trashed("discarded", False)
    repo.set_trashed("discarded", False)
    restored = repo.get("discarded")
    for field in ("title", "status", "rating", "is_favorite", "category", "last_opened_at", "current_segment_index"):
        assert restored[field] == before[field]
    assert restored["summarize_intent"] == "paused"
    assert restored["trashed_at"] is None
    assert repo.list_books(visibility="trash") == []
    assert {r["kind"] for r in search(conn, "TRASHNEEDLE")} == {"book", "note"}
    assert len(NoteRepo(conn).list_all()) == 1


def test_assistant_results_and_tag_actions_cannot_reveal_trash(library):
    conn, repo, _ = library
    result = execute_plan(conn, LibraryPlan(action="add_tag", tag="待读"))
    applied = apply_action(conn, result["result_id"])
    assert applied["book_count"] == 1
    assert list_tags(conn)[0]["book_count"] == 1
    pending = execute_plan(conn, LibraryPlan(action="add_tag", tag="稍后"))
    repo.set_trashed("discarded", True)
    assert execute_plan(conn, LibraryPlan())["total"] == 0
    assert list_tags(conn)[0]["book_count"] == 0
    for result_id in (result["result_id"], pending["result_id"]):
        with pytest.raises(ValueError, match="已变化"):
            apply_action(conn, result_id)
        with pytest.raises(ValueError, match="已变化"):
            execute_plan(conn, LibraryPlan(scope="previous"), result_id)


@pytest.mark.asyncio
async def test_restart_and_explicit_start_never_schedule_trash(library):
    conn, repo, _ = library
    repo.set_trashed("discarded", True)
    queue = JobQueue(conn, MockModelRouter())
    assert queue.is_user_paused("discarded")
    assert sum(queue.summarize_overview()["counts"].values()) == 0
    await queue.begin_start_book("discarded")
    await queue.enqueue_book_prefetch("discarded")
    await queue.enqueue_rollup("discarded")
    await queue._run_intro("discarded", force=True)
    assert not queue.has_book_work("discarded")
    assert repo.get("discarded")["summarize_intent"] == "paused"
    assert not queue._start_tasks


def test_cancel_pending_intro_keeps_saved_content(library):
    conn, _, _ = library
    intros = BookIntroRepo(conn)
    intros.upsert("discarded", status="pending", source_text="Saved source",
                  summary_json={"sentences": ["Saved intro"]})
    intros.reset_pending("discarded")
    intro = intros.get("discarded")
    assert intro["status"] == "ready"
    assert intro["source_text"] == "Saved source"
    assert intro["summary"]["sentences"] == ["Saved intro"]
    intros.upsert("discarded", status="pending")
    intros.reset_pending("discarded")
    assert intros.get("discarded")["status"] == "idle"
