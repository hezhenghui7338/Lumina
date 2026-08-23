"""Context probe: later segments must still be understood."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumina_core.config import ModelResource, Settings
from lumina_core.main import create_app
from lumina_core.models.context_probe import (
    CONTEXT_PROBE_CAP,
    CONTEXT_PROBE_FLOOR,
    ContextProbeStatus,
    build_probe_passage,
    facts_match,
    recommend_chunk_target,
    run_context_probe,
)
from lumina_core.models.router import set_router
from tests.support.mock_router import MockModelRouter, load_json_fixture

LLM_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "llm"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMINA_DATA_DIR", str(tmp_path))
    router = MockModelRouter(
        responses={
            "summarize": load_json_fixture(LLM_FIXTURES / "summary_segment0.json"),
        }
    )
    app = create_app(Settings(data_dir=tmp_path))
    app.state.lumina.router = router
    app.state.lumina.job_queue.router = router
    set_router(router)
    with TestClient(app) as c:
        yield c


def _wait_probe(client: TestClient, resource_id: str = "ollama", timeout: float = 8.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = client.get(f"/settings/resources/{resource_id}/context-probe").json()
        if payload["status"] != "running":
            return payload
        time.sleep(0.05)
    raise AssertionError(f"probe still running: {payload}")


def test_recommend_chunk_target_formula():
    assert recommend_chunk_target(0) == CONTEXT_PROBE_FLOOR
    assert recommend_chunk_target(1500) == CONTEXT_PROBE_FLOOR
    assert recommend_chunk_target(2000) == 1600
    assert recommend_chunk_target(5000) == CONTEXT_PROBE_CAP
    assert recommend_chunk_target(4375) == CONTEXT_PROBE_CAP


def test_passage_plants_first_and_last_facts():
    passage = build_probe_passage(2500, rng=__import__("random").Random(0))
    assert passage.segment_count >= 2
    assert passage.first in passage.segments[0]
    assert passage.last in passage.segments[-1]
    assert passage.first not in passage.segments[-1]
    assert passage.last not in passage.segments[0]
    assert abs(len(passage.body) - 2500) <= passage.segment_count


def test_facts_match_requires_both_json_fields():
    assert facts_match('{"first":"沈北川","last":"青瓷铃"}', "沈北川", "青瓷铃")
    assert not facts_match('{"first":"沈北川","last":"错"}', "沈北川", "青瓷铃")
    assert not facts_match('{"first":"沈北川"}', "沈北川", "青瓷铃")
    assert not facts_match("沈北川 青瓷铃", "沈北川", "青瓷铃")


@pytest.mark.asyncio
async def test_drop_last_stops_at_first_rung():
    router = MockModelRouter()
    router.pinned_drop_last = True
    resource = ModelResource(id="ollama", provider="ollama", model="qwen3.5:4b")
    status = ContextProbeStatus(resource_id="ollama", model=resource.model)
    await run_context_probe(
        router=router,
        resource=resource,
        status=status,
        cancel_event=asyncio.Event(),
    )
    assert status.status == "done"
    assert status.max_ok_chars is None
    assert status.recommended_chars == CONTEXT_PROBE_FLOOR
    assert status.steps
    assert status.steps[0]["ok"] is False
    assert "末段" in (status.steps[0]["message"] or "")
    assert all(call["method"] == "complete_pinned" for call in router.calls)
    assert all(call["resource_id"] == "ollama" for call in router.calls)
    assert not any(call["method"] == "complete" for call in router.calls)


@pytest.mark.asyncio
async def test_fail_over_chars_keeps_last_success():
    router = MockModelRouter()
    router.pinned_fail_over_chars = 2000
    resource = ModelResource(id="ollama", provider="ollama", model="qwen3.5:4b")
    status = ContextProbeStatus(resource_id="ollama")
    await run_context_probe(
        router=router,
        resource=resource,
        status=status,
        cancel_event=asyncio.Event(),
    )
    assert status.max_ok_chars == 2000
    assert status.recommended_chars == 1600
    assert [step["chars"] for step in status.steps] == [1500, 2000, 2500]
    assert status.steps[-1]["ok"] is False


@pytest.mark.asyncio
async def test_cancel_stops_later_rungs():
    router = MockModelRouter()
    router.pinned_delay_s = 0.4
    resource = ModelResource(id="ollama", provider="ollama", model="qwen3.5:4b")
    status = ContextProbeStatus(resource_id="ollama")
    cancel_event = asyncio.Event()

    async def _cancel_soon() -> None:
        await asyncio.sleep(0.05)
        cancel_event.set()

    await asyncio.gather(
        run_context_probe(
            router=router,
            resource=resource,
            status=status,
            cancel_event=cancel_event,
        ),
        _cancel_soon(),
    )
    assert status.status == "cancelled"
    assert len(router.calls) <= 2


def test_post_returns_202_without_waiting_for_llm(client):
    client.app.state.lumina.router.pinned_delay_s = 2.0
    started = time.perf_counter()
    response = client.post("/settings/resources/ollama/context-probe", json={})
    elapsed = time.perf_counter() - started
    assert response.status_code == 202
    assert elapsed < 0.8
    duplicate = client.post("/settings/resources/ollama/context-probe", json={})
    assert duplicate.status_code == 409
    cancel = client.post("/settings/resources/ollama/context-probe/cancel")
    assert cancel.status_code == 202


def test_get_idle_and_missing_resource(client):
    idle = client.get("/settings/resources/ollama/context-probe")
    assert idle.status_code == 200
    assert idle.json()["status"] == "idle"
    missing = client.get("/settings/resources/no-such/context-probe")
    assert missing.status_code == 404


def test_probe_applies_recommendation_without_writing_settings(client):
    before = client.get("/settings").json()
    ollama = next(r for r in before["models"]["resources"] if r["id"] == "ollama")
    original = ollama.get("chunk_target_chars") or 0
    started = client.post("/settings/resources/ollama/context-probe", json={})
    assert started.status_code == 202
    done = _wait_probe(client)
    assert done["status"] == "done"
    assert done["recommended_chars"] == CONTEXT_PROBE_CAP
    after = client.get("/settings").json()
    still = next(r for r in after["models"]["resources"] if r["id"] == "ollama")
    assert (still.get("chunk_target_chars") or 0) == original


def test_pinned_failure_does_not_call_complete_fallback(client):
    router = client.app.state.lumina.router
    router.pinned_fail_ids.add("ollama")
    client.post("/settings/resources/ollama/context-probe", json={})
    done = _wait_probe(client)
    assert done["status"] == "done"
    assert done["recommended_chars"] == CONTEXT_PROBE_FLOOR
    assert all(call.get("resource_id") == "ollama" for call in router.calls)
    assert not any(call["method"] == "complete" for call in router.calls)
