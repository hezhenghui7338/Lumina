"""segment_ready SSE payload tests."""

from __future__ import annotations

import json
from pathlib import Path

from lumina_core.summarize.schema import parse_segment_summary
from lumina_core.summarize.segment import segment_ready_event_payload

LLM_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "llm"


def test_segment_ready_event_payload_includes_flat_fields():
    raw = (LLM_FIXTURES / "summary_segment0.json").read_text(encoding="utf-8")
    summary = parse_segment_summary(raw)
    payload = segment_ready_event_payload(
        summary,
        idx=2,
        resource_id="openrouter",
        model="gpt-4o-mini",
    )

    assert payload["type"] == "segment_ready"
    assert payload["idx"] == 2
    assert payload["summary_status"] == "ready"
    assert payload["summary_provider"] == "openrouter"
    assert payload["summary_model"] == "gpt-4o-mini"
    assert payload["sentences"] == summary.sentences
    assert payload["bullets"] == [b.model_dump() for b in summary.bullets]
    assert payload["notes"] == summary.notes
    assert payload["follow_ups"] == summary.follow_ups
    assert payload["anchor"] == summary.anchor
    assert payload["anchor_label"] == summary.anchor

    nested = json.loads(payload["summary_json"])
    assert nested["sentences"] == summary.sentences
    assert nested["label"] == summary.label
