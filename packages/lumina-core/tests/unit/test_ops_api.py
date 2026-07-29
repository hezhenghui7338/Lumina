"""Ops API unit tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lumina_core.main import create_app
from lumina_core.ops.task_registry import TaskRegistry


@pytest.fixture
def client(tmp_path):
    from lumina_core.config import Settings

    settings = Settings(data_dir=tmp_path)
    app = create_app(settings)
    return TestClient(app)


def _enable_debug(client: TestClient) -> None:
    state = client.app.state.lumina
    state.settings.debug_mode = True


def test_ops_overview_requires_debug_mode(client):
    resp = client.get("/ops/overview")
    assert resp.status_code == 403


def test_ops_overview(client):
    _enable_debug(client)
    resp = client.get("/ops/overview")
    assert resp.status_code == 200
    data = resp.json()
    assert "task_counts" in data
    assert "job_queue" in data
    assert "resource_runtime" in data
    jq = data["job_queue"]
    assert "queue_depth" in jq
    assert "paused_backlog_depth" in jq
    assert "chat_preempted" in jq
    assert "worker_target" in jq
    assert "worker_count" in jq
    assert "active_jobs" in jq
    assert jq["chat_preempted"] is False
    assert "paused" in data["task_counts"]
    assert data["last_call"] is None or isinstance(data["last_call"], dict)


def test_ops_overview_job_queue_diagnostics_fields(client):
    """Summarize diagnostics: queue depth, chat preemption, worker target."""
    _enable_debug(client)
    state = client.app.state.lumina
    diag = state.job_queue.diagnostics()
    assert set(diag) >= {
        "queue_depth",
        "active_jobs",
        "paused_backlog_depth",
        "worker_count",
        "worker_target",
        "chat_preempted",
        "user_paused_all",
        "user_paused_books",
    }
    assert diag["chat_preempted"] is False
    state.job_queue.pause_ollama()
    assert state.job_queue.diagnostics()["chat_preempted"] is True
    state.job_queue.resume_ollama()
    assert state.job_queue.diagnostics()["chat_preempted"] is False


def test_ops_tasks_track_summarize_metrics(client):
    """Task registry exposes llm_attempt and duration_s for summarize jobs."""
    _enable_debug(client)
    state = client.app.state.lumina
    job_key = "b1:seg1:summarize"
    record = state.task_registry.register(
        kind="summarize",
        subject_type="book",
        subject_id="b1",
        subject_label="Test Book",
        detail="段 1 摘要",
        profile="summarize",
        status="running",
        job_key=job_key,
    )
    state.task_registry.update_progress_by_job_key(
        job_key,
        llm_attempt=2,
        max_llm_attempts=2,
        duration_s=45.5,
    )
    state.task_registry.update_resource(record.id, "ollama")
    resp = client.get("/ops/tasks?kind=summarize")
    assert resp.status_code == 200
    tasks = resp.json()["tasks"]
    task = next(t for t in tasks if t["id"] == record.id)
    assert task["resource_id"] == "ollama"
    assert task["llm_attempt"] == 2
    assert task["max_llm_attempts"] == 2
    assert task["duration_s"] == 45.5


def test_ops_tasks_empty(client):
    _enable_debug(client)
    resp = client.get("/ops/tasks")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tasks"] == []
    assert data["counts"]["running"] == 0


def test_ops_register_and_list(client):
    _enable_debug(client)
    state = client.app.state.lumina
    registry: TaskRegistry = state.task_registry
    record = registry.register(
        kind="news_read",
        subject_type="article",
        subject_id="a1",
        subject_label="Article",
        detail="资讯精读",
        status="running",
        cancellable=True,
        cancel_fn=lambda: None,
    )
    resp = client.get("/ops/tasks?status=running")
    assert resp.status_code == 200
    tasks = resp.json()["tasks"]
    assert any(t["id"] == record.id for t in tasks)

    cancel = client.post(f"/ops/tasks/{record.id}/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"


def test_ops_cancel_not_cancellable(client):
    _enable_debug(client)
    state = client.app.state.lumina
    record = state.task_registry.register(
        kind="summarize",
        subject_type="book",
        subject_id="b1",
        subject_label="Book",
        detail="段 1",
        status="running",
        cancellable=False,
    )
    resp = client.post(f"/ops/tasks/{record.id}/cancel")
    assert resp.status_code == 400


def test_ops_resources_runtime(client):
    _enable_debug(client)
    resp = client.get("/ops/resources/runtime")
    assert resp.status_code == 200
    data = resp.json()
    assert "resources" in data
    assert "last_call" in data
