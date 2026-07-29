"""Tests for summarize duration and attempt metrics."""

from __future__ import annotations

import json

import pytest

from lumina_core.config import ModelResource, ModelsConfig, ProfileRoute
from lumina_core.models.router import ProfileModelRouter
from lumina_core.summarize.schema import SegmentSummary
from lumina_core.summarize.segment import (
    SummarizeResult,
    segment_ready_event_payload,
    summarize_segment,
)

_VALID_SUMMARY = {
    "sentences": ["一句概述。"],
    "bullets": [
        {"label": "要点一", "body": "第一条要点的充实说明，包含足够细节内容。"},
        {"label": "要点二", "body": "第二条要点的充实说明，包含足够细节内容。"},
        {"label": "要点三", "body": "第三条要点的充实说明，包含足够细节内容。"},
    ],
    "label": "测试段",
    "anchor": "§段 1",
}

_MINIMAL_SUMMARY = {
    "sentences": ["一句概述。"],
    "bullets": [
        {"label": "要点一", "body": "第一条要点的充实说明，包含足够细节内容。"},
        {"label": "要点二", "body": "第二条要点的充实说明，包含足够细节内容。"},
        {"label": "要点三", "body": "第三条要点的充实说明，包含足够细节内容。"},
    ],
}


@pytest.mark.asyncio
async def test_summarize_segment_returns_attempt_metrics():
    class RetryRouter:
        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, prompt, profile="summarize", json_mode=True):
            self.calls += 1
            if self.calls == 1:
                return "not json"
            return json.dumps(_VALID_SUMMARY)

    events: list[dict] = []

    async def on_progress(payload: dict) -> None:
        events.append(payload)

    result = await summarize_segment(
        RetryRouter(),
        raw_text="hello",
        anchor_label="§段 1",
        max_retries=2,
        on_progress=on_progress,
    )

    assert isinstance(result, SummarizeResult)
    assert result.llm_attempts == 2
    assert result.llm_duration_s >= 0
    assert result.summary.label == "测试段"
    assert any(event["type"] == "segment_summarize_progress" for event in events)
    assert events[0]["llm_attempt"] == 1
    assert events[-1]["phase"] == "start"


@pytest.mark.asyncio
async def test_ollama_summarize_uses_json_mode():
    class CaptureRouter(ProfileModelRouter):
        json_modes: list[bool] = []

        async def complete(self, prompt, profile="summarize", json_mode=True):
            type(self).json_modes.append(json_mode)
            return json.dumps(_MINIMAL_SUMMARY)

    router = CaptureRouter(
        ModelsConfig(
            resources=[
                ModelResource(
                    id="ollama",
                    provider="ollama",
                    base_url="http://127.0.0.1:11434",
                    model="qwen3.5:4b",
                )
            ],
            summarize=ProfileRoute(priority=["ollama"]),
        )
    )
    CaptureRouter.json_modes = []

    result = await summarize_segment(
        router,
        raw_text="hello",
        anchor_label="§段 1",
    )

    assert CaptureRouter.json_modes == [True]
    assert result.summary.label == "一句概述"
    assert result.summary.anchor == "§段 1"
    assert result.summary.notes == []


def test_segment_ready_payload_includes_metrics():
    summary = SegmentSummary.model_validate(_VALID_SUMMARY)
    payload = segment_ready_event_payload(
        summary,
        idx=3,
        resource_id="ollama",
        model="qwen3.5:4b",
        summary_duration_s=62.5,
        summary_llm_attempts=2,
    )
    assert payload["summary_duration_s"] == 62.5
    assert payload["summary_llm_attempts"] == 2
    assert payload["idx"] == 3
