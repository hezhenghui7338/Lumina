"""TaskRegistry unit tests."""

from __future__ import annotations

import time

from lumina_core.ops.task_registry import TaskRegistry


def test_register_and_complete():
    registry = TaskRegistry()
    record = registry.register(
        kind="summarize",
        subject_type="book",
        subject_id="b1",
        subject_label="Test Book",
        detail="段 1 摘要",
        profile="summarize",
        job_key="b1:seg1:summarize",
    )
    assert record.status == "queued"
    registry.mark_running(record.id, resource_id="ollama")
    registry.complete(record.id)
    snap = registry.snapshot()
    assert len(snap) == 1
    assert snap[0]["status"] == "completed"
    assert snap[0]["resource_id"] == "ollama"


def test_mark_running_resets_started_at_and_duration():
    registry = TaskRegistry()
    record = registry.register(
        kind="summarize",
        subject_type="book",
        subject_id="b1",
        subject_label="Test Book",
        detail="段 1 摘要",
        profile="summarize",
        job_key="b1:seg1:summarize",
    )
    queued_started_at = record.started_at
    registry.update_progress_by_job_key(
        "b1:seg1:summarize",
        duration_s=12.5,
        llm_attempt=1,
    )
    time.sleep(0.01)
    registry.mark_running(record.id, resource_id="ollama")
    running = registry.get(record.id)
    assert running is not None
    assert running.status == "running"
    assert running.started_at != queued_started_at
    assert running.duration_s is None
    assert running.resource_id == "ollama"


def test_job_key_lookup_and_cancel():
    registry = TaskRegistry()
    record = registry.register(
        kind="book_chat",
        subject_type="book",
        subject_id="b1",
        subject_label="Book",
        detail="深聊",
        cancellable=True,
        cancel_fn=lambda: None,
        job_key="chat-1",
        status="running",
    )
    assert registry.get_by_job_key("chat-1") is record
    assert registry.cancel(record.id) is True
    assert registry.get(record.id).status == "cancelled"


def test_fail_and_counts():
    registry = TaskRegistry()
    record = registry.register(
        kind="classify",
        subject_type="book",
        subject_id="b1",
        subject_label="Book",
        detail="LLM 分类",
        status="running",
    )
    registry.fail(record.id, "boom")
    counts = registry.counts()
    assert counts["failed"] == 1
    assert registry.get(record.id).error == "boom"


def test_pause_and_requeue_by_job_key():
    registry = TaskRegistry()
    record = registry.register(
        kind="summarize",
        subject_type="book",
        subject_id="b1",
        subject_label="Book",
        detail="段 1 摘要",
        job_key="b1:seg1:summarize",
    )
    registry.mark_running(record.id)
    assert registry.pause_by_job_key("b1:seg1:summarize") is True
    assert registry.get(record.id).status == "paused"
    assert registry.get_by_job_key("b1:seg1:summarize") is record

    assert registry.requeue_by_job_key("b1:seg1:summarize") is True
    assert registry.get(record.id).status == "queued"


def test_pause_clears_duration():
    registry = TaskRegistry()
    record = registry.register(
        kind="summarize",
        subject_type="book",
        subject_id="b1",
        subject_label="Book",
        detail="段 1 摘要",
        job_key="b1:seg1:summarize",
    )
    registry.mark_running(record.id)
    registry.update_progress_by_job_key("b1:seg1:summarize", duration_s=30.0)
    registry.pause(record.id)
    paused = registry.get(record.id)
    assert paused is not None
    assert paused.status == "paused"
    assert paused.duration_s is None


def test_counts_includes_paused():
    registry = TaskRegistry()
    record = registry.register(
        kind="summarize",
        subject_type="book",
        subject_id="b1",
        subject_label="Book",
        detail="段 1",
        job_key="b1:seg1:summarize",
    )
    registry.pause(record.id)
    counts = registry.counts()
    assert counts["paused"] == 1
    assert counts["queued"] == 0


def test_completed_ring_buffer():
    registry = TaskRegistry(completed_limit=2)
    for i in range(4):
        r = registry.register(
            kind="summarize",
            subject_type="book",
            subject_id=f"b{i}",
            subject_label=f"Book {i}",
            detail=f"段 {i}",
            status="running",
        )
        registry.complete(r.id)
    completed = [t for t in registry.snapshot() if t["status"] == "completed"]
    assert len(completed) == 4
