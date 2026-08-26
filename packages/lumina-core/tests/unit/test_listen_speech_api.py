"""Listen-script API: never load raw_text for summary modes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumina_core.config import Settings
from lumina_core.db.repos import BookRepo, SegmentRepo
from lumina_core.main import create_app
from lumina_core.models.router import set_router
from tests.support.mock_router import MockModelRouter, load_json_fixture

LLM_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "llm"

SAMPLE_SUMMARY = {
    "sentences": ["本段交代主角出身寒门。"],
    "bullets": [
        {"label": "寒门出身", "body": "主角生于贫苦农家，父亲早逝。"},
        {"label": "赴考之志", "body": "段末以金榜题名收束。"},
        {"label": "邻里期望", "body": "乡邻视为村庄的希望。"},
    ],
    "notes": ["后文冲突。"],
    "follow_ups": ["不该被朗读的追问？"],
    "label": "引子",
    "anchor": "§一 · 段 1",
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMINA_DATA_DIR", str(tmp_path))
    router = MockModelRouter(
        responses={
            "summarize": load_json_fixture(LLM_FIXTURES / "summary_segment0.json"),
            "chat": "{}",
            "translate": "示例译文。",
        }
    )
    app = create_app(Settings(data_dir=tmp_path))
    app.state.lumina.router = router
    app.state.lumina.job_queue.router = router
    set_router(router)
    with TestClient(app) as c:
        yield c


def _seed_segment(client: TestClient, *, status: str = "ready") -> str:
    conn = client.app.state.lumina.conn  # type: ignore[attr-defined]
    BookRepo(conn).insert(
        id="listen-book",
        title="Listen",
        format="txt",
        file_path="/tmp/listen.txt",
        segment_count=1,
        status="reading",
    )
    SegmentRepo(conn).insert_many(
        [
            {
                "id": "listen-seg-0",
                "book_id": "listen-book",
                "idx": 0,
                "chapter": None,
                "page_range": None,
                "anchor_label": "a",
                "raw_text": "SECRET_RAW_TEXT_SHOULD_NOT_LEAK",
                "summary_status": status,
                "retry_count": 0,
            }
        ]
    )
    if status == "ready":
        SegmentRepo(conn).update_summary(
            "listen-seg-0",
            summary_json=json.dumps(SAMPLE_SUMMARY, ensure_ascii=False),
            label="引子",
            status="ready",
        )
    return "listen-book"


def test_listen_script_summary_omits_follow_ups(client):
    book_id = _seed_segment(client)
    payload = client.get(
        f"/books/{book_id}/segments/0/listen-script",
        params={"mode": "summary"},
    ).json()
    assert payload["ready"] is True
    texts = [u["text"] for u in payload["utterances"]]
    assert texts == SAMPLE_SUMMARY["sentences"]
    joined = "\n".join(texts)
    assert "不该被朗读的追问" not in joined
    assert "SECRET_RAW_TEXT" not in joined


def test_listen_script_detailed_has_bullets_not_follow_ups(client):
    book_id = _seed_segment(client)
    payload = client.get(
        f"/books/{book_id}/segments/0/listen-script",
        params={"mode": "detailed"},
    ).json()
    texts = [u["text"] for u in payload["utterances"]]
    assert "结构化要点" in texts
    assert any(t.startswith("1. 寒门出身。") for t in texts)
    assert "需要注意" not in texts
    joined = "\n".join(texts)
    assert "后文冲突。" not in joined
    assert "不该被朗读的追问" not in joined


def test_listen_script_original_uses_raw_text(client):
    book_id = _seed_segment(client)
    payload = client.get(
        f"/books/{book_id}/segments/0/listen-script",
        params={"mode": "original"},
    ).json()
    assert payload["ready"] is True
    joined = " ".join(u["text"] for u in payload["utterances"])
    assert "SECRET_RAW_TEXT_SHOULD_NOT_LEAK" in joined


def test_listen_script_summary_skips_when_not_ready(client):
    book_id = _seed_segment(client, status="pending")
    payload = client.get(
        f"/books/{book_id}/segments/0/listen-script",
        params={"mode": "summary"},
    ).json()
    assert payload["ready"] is False
    assert payload["skip_reason"] == "summary_not_ready"
    assert payload["utterances"] == []


def test_listen_script_summary_never_calls_get_by_index(client, monkeypatch):
    book_id = _seed_segment(client)

    def boom(self, book_id, idx):  # noqa: ARG001
        raise AssertionError("get_by_index must not run for summary listen-script")

    monkeypatch.setattr(SegmentRepo, "get_by_index", boom)
    resp = client.get(
        f"/books/{book_id}/segments/0/listen-script",
        params={"mode": "detailed"},
    )
    assert resp.status_code == 200
    assert resp.json()["ready"] is True


def test_speech_endpoint_removed(client):
    book_id = _seed_segment(client)
    resp = client.post(
        f"/books/{book_id}/segments/0/speech",
        json={"mode": "summary", "utterance_index": 0},
    )
    assert resp.status_code == 404
