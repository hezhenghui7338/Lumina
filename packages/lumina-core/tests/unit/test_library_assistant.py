"""Queries run against metadata; tag changes require a frozen result preview."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from lumina_core.api.library_routes import router
from lumina_core.db.schema import init_db
from lumina_core.library_assistant import (
    LibraryFilter, LibraryPlan, apply_action, ask_library, book_tags, delete_tag, execute_plan,
    list_tags, record_open, save_tag,
)
from tests.support.mock_router import MockModelRouter


@pytest.fixture
def conn(tmp_path):
    db = init_db(tmp_path / "library.db")
    for i, title, author, lang, count, status, current in [
        ("b1", "Norwegian Wood", "村上春树", "en-US", 299, "unread", 0),
        ("b2", "海边的卡夫卡", "村上春树", "zh-CN", 300, "reading", 149),
        ("b3", "Other", "Someone", "en", 20, "finished", 19),
    ]:
        db.execute("INSERT INTO books(id,title,author,language,segment_count,status,current_segment_index,format,file_path,created_at,updated_at,summary_total_count,summary_ready_count,metadata_json) VALUES(?,?,?,?,?,?,?,'txt','/x','2026-10-01','now',20,20,?)",
                   (i, title, author, lang, count, status, current, json.dumps({"publication_year": 2001, "description": "brief"})))
        db.execute("INSERT INTO segments(id,book_id,idx,raw_text) VALUES(?,?,0,'SECRET BOOK BODY')", ("s" + i, i))
    for i, kind, text in [(1, "highlight", ""), (2, "manual", "SECRET COMMENT"), (3, "highlight", "")]:
        db.execute("INSERT INTO notes(id,book_id,segment_id,type,content,created_at) VALUES(?,'b2','sb2',?,?,'now')", (str(i), kind, text))
    db.execute("UPDATE books SET last_opened_at='2026-10-01' WHERE id IN ('b2','b3')")
    db.commit()
    yield db
    db.close()


def plan(**kwargs):
    return LibraryPlan.model_validate(kwargs)


def test_language_segment_boundary_author_and_note_counts(conn):
    english = execute_plan(conn, plan(filters=[{"field": "language", "value": "英文"}]))
    assert english["total"] == 2
    short = execute_plan(conn, plan(filters=[{"field": "segment_count", "op": "lt", "value": 300}]))
    assert {b["id"] for b in short["books"]} == {"b1", "b3"}
    author = execute_plan(conn, plan(filters=[{"field": "author", "op": "contains", "value": "村上春树"}], sort="highlight_count"))
    assert author["total"] == 2
    assert author["books"][0]["id"] == "b2"
    assert author["books"][0]["highlight_count"] == 2
    assert author["books"][0]["comment_count"] == 1
    assert author["books"][0]["reading_progress"] == pytest.approx(149 / 300 * 100)
    assert author["books"][0]["published_year"] == 2001


def test_followup_scope_is_frozen_and_tag_action_is_explicit_idempotent(conn):
    first = execute_plan(conn, plan(filters=[{"field": "language", "value": "en"}]))
    conn.execute("UPDATE books SET language='en' WHERE id='b2'")
    conn.commit()
    follow = execute_plan(conn, plan(scope="previous", filters=[{"field": "status", "value": "unread"}], action="add_tag", tag="英文待读"), first["result_id"])
    assert [b["id"] for b in follow["books"]] == ["b1"]
    assert list_tags(conn) == []  # Preview never mutates tags.
    applied = apply_action(conn, follow["result_id"])
    assert applied["book_count"] == 1
    assert apply_action(conn, follow["result_id"]) == applied
    assert list_tags(conn)[0]["book_count"] == 1
    assert book_tags(conn) == {"b1": ["英文待读"]}
    found = execute_plan(conn, plan(filters=[{"field": "tag", "value": "英文待读"}]))
    assert found["books"][0]["tags"] == ["英文待读"]


def test_tag_rename_remove_and_delete_do_not_delete_books(conn):
    found = execute_plan(conn, plan(action="add_tag", tag="Reading"))
    apply_action(conn, found["result_id"])
    tag = list_tags(conn)[0]
    save_tag(conn, "待读", tag["id"])
    assert list_tags(conn)[0]["book_count"] == 3
    remove = execute_plan(conn, plan(action="remove_tag", tag="待读", filters=[{"field": "title", "value": "Other"}]))
    apply_action(conn, remove["result_id"])
    assert list_tags(conn)[0]["book_count"] == 2
    delete_tag(conn, tag["id"])
    assert list_tags(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 3


def test_stale_tag_or_deleted_book_requires_new_preview(conn):
    save_tag(conn, "old")
    pending = execute_plan(conn, plan(action="add_tag", tag="old"))
    save_tag(conn, "new", list_tags(conn)[0]["id"])
    with pytest.raises(ValueError, match="改名"):
        apply_action(conn, pending["result_id"])
    pending = execute_plan(conn, plan(action="add_tag", tag="new"))
    conn.execute("DELETE FROM books WHERE id='b1'")
    conn.commit()
    with pytest.raises(ValueError, match="书籍已变化"):
        apply_action(conn, pending["result_id"])


def test_expired_or_missing_previous_and_actions_fail_closed(conn):
    with pytest.raises(ValueError):
        execute_plan(conn, plan(scope="previous"))
    found = execute_plan(conn, LibraryPlan())
    with pytest.raises(ValueError):
        apply_action(conn, found["result_id"])
    conn.execute("UPDATE library_query_results SET expires_at='2000-01-01' WHERE id=?", (found["result_id"],))
    conn.commit()
    with pytest.raises(ValueError, match="过期"):
        execute_plan(conn, plan(scope="previous"), found["result_id"])


def test_sql_injection_is_literal_and_untrusted_fields_rejected(conn):
    found = execute_plan(conn, plan(filters=[{"field": "title", "op": "contains", "value": "' OR 1=1 --"}]))
    assert found["total"] == 0
    for invalid in [
        {"filters": [{"field": "raw_text", "value": "secret"}]},
        {"sql": "DELETE FROM books"},
        {"filters": [{"field": "segment_count", "op": "contains", "value": 20}]},
        {"filters": [{"field": "summary_complete", "value": "true"}]},
        {"filters": [{"field": "open_count", "value": True}]},
    ]:
        with pytest.raises(ValidationError):
            plan(**invalid)


def test_open_counts_are_real_and_unknown_years_do_not_match(conn):
    record_open(conn, "b1")
    record_open(conn, "b1")
    result = execute_plan(conn, plan(sort="open_count"))
    assert result["books"][0]["id"] == "b1"
    assert result["books"][0]["open_count"] == 2
    conn.execute("UPDATE books SET metadata_json='{}' WHERE id='b1'")
    conn.commit()
    result = execute_plan(conn, plan(filters=[{"field": "published_year", "op": "lt", "value": 1900}]))
    assert result["total"] == 0
    conn.execute("UPDATE books SET metadata_json=? WHERE id='b1'", (json.dumps({"publication_year": "unknown"}),))
    conn.commit()
    assert execute_plan(conn, plan(filters=[{"field": "published_year", "op": "lt", "value": 1900}]))["total"] == 0


@pytest.mark.asyncio
async def test_model_only_sees_schema_question_and_previous_plan(conn):
    model = MockModelRouter(responses={"chat": {"filters": [{"field": "author", "op": "contains", "value": "村上春树"}]}})
    result = await ask_library(conn, model, "我有哪些村上春树的书？")
    assert result["total"] == 2
    prompt = model.calls[0]["prompt"]
    assert "SECRET BOOK BODY" not in prompt
    assert "SECRET COMMENT" not in prompt
    assert "Norwegian Wood" not in prompt


@pytest.mark.asyncio
async def test_common_count_queries_do_not_require_model(conn):
    model = MockModelRouter()
    assert (await ask_library(conn, model, "我有多少本英文书？"))["total"] == 2
    assert (await ask_library(conn, model, "我有多少本300段以下的书？"))["total"] == 2
    assert model.calls == []


@pytest.mark.asyncio
async def test_recent_reading_excludes_never_opened_books_and_tags_work_offline(conn):
    conn.execute("UPDATE books SET last_opened_at='2026-10-29' WHERE id='b2'")
    conn.commit()
    model = MockModelRouter()
    recent = await ask_library(conn, model, "我最近读过哪些书？")
    assert [b["id"] for b in recent["books"]] == ["b2", "b3"]
    apply_action(conn, execute_plan(conn, plan(action="add_tag", tag="喜欢的书"))["result_id"])
    assert (await ask_library(conn, model, "有哪些带“喜欢的书”标签的书？"))["total"] == 3
    assert model.calls == []


@pytest.mark.asyncio
async def test_empty_model_plan_fails_instead_of_selecting_every_book(conn):
    with pytest.raises(ValueError, match="没有识别"):
        await ask_library(conn, MockModelRouter(responses={"chat": {}}), "无法理解的表达")


def test_reading_state_matches_shelf_even_after_summary_completion(conn):
    conn.execute("UPDATE books SET status='summarized'")
    conn.commit()
    assert [b["id"] for b in execute_plan(conn, plan(filters=[{"field": "status", "value": "unread"}]))["books"]] == ["b1"]
    assert [b["id"] for b in execute_plan(conn, plan(filters=[{"field": "status", "value": "finished"}]))["books"]] == ["b3"]
    conn.execute("UPDATE books SET segment_count=1, current_segment_index=0 WHERE id='b3'")
    conn.commit()
    reading = execute_plan(conn, plan(filters=[{"field": "status", "value": "reading"}]))
    assert {b["id"] for b in reading["books"]} == {"b2", "b3"}
    assert next(b for b in reading["books"] if b["id"] == 'b3')["reading_progress"] == 0


def test_deleting_book_cleans_tags_and_open_counts(conn):
    record_open(conn, "b1")
    apply_action(conn, execute_plan(conn, plan(action="add_tag", tag="test"))["result_id"])
    conn.execute("DELETE FROM books WHERE id='b1'")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM library_reading_stats WHERE book_id='b1'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM library_book_tags WHERE book_id='b1'").fetchone()[0] == 0
    assert list_tags(conn)[0]["book_count"] == 2


def test_result_limit_does_not_limit_batch_tag_targets(conn):
    for i in range(105):
        conn.execute("INSERT INTO books(id,title,format,file_path,created_at,updated_at) VALUES(?,?,'txt','/x','now','now')", (f"extra{i}", f"Extra{i}"))
    conn.commit()
    found = execute_plan(conn, plan(action="add_tag", tag="全部"))
    assert found["total"] == 108 and len(found["books"]) == 100
    assert apply_action(conn, found["result_id"])["book_count"] == 108
    assert list_tags(conn)[0]["book_count"] == 108


def test_api_metadata_query_preview_apply_and_validation(conn):
    app = FastAPI()
    app.state.lumina = SimpleNamespace(conn=conn, router=MockModelRouter())
    app.include_router(router)
    with TestClient(app) as client:
        result = client.post("/library/ask", json={"message": "我有多少本英文书？"}).json()
        assert result["total"] == 2
        preview = client.post(f"/library/results/{result['result_id']}/preview-tag", json={"name": "English"})
        assert preview.status_code == 200
        assert client.get("/library/tags").json()["tags"] == []
        result_id = preview.json()["result_id"]
        assert client.post(f"/library/results/{result_id}/apply").json()["book_count"] == 2
        tag = client.get("/library/tags").json()["tags"][0]
        assert client.patch(f"/library/tags/{tag['id']}", json={"name": "英语"}).status_code == 200
        assert client.delete(f"/library/tags/{tag['id']}").json()["tags"] == []
        assert client.post("/library/ask", json={"message": "  "}).status_code == 422
        assert client.post("/library/results/missing/apply").status_code == 409


def test_schema_reinitialization_preserves_tags(tmp_path):
    path = tmp_path / "upgrade.db"
    first = init_db(path)
    save_tag(first, "保留")
    first.close()
    second = init_db(path)
    assert list_tags(second)[0]["name"] == "保留"
    second.close()
