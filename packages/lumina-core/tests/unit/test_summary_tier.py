"""Normal/advanced summary model selection and persistence."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from lumina_core.config import ModelResource, ModelsConfig, ProfileRoute
from lumina_core.db.repos import BookRepo, SegmentRepo
from lumina_core.db.schema import init_db
from lumina_core.models.router import ProfileModelRouter


def test_advanced_model_falls_back_to_normal_model():
    resource = ModelResource(
        id="ollama", provider="ollama", model="normal-model"
    )
    assert resource.summary_model("normal") == "normal-model"
    assert resource.summary_model("advanced") == "normal-model"


@pytest.mark.asyncio
async def test_router_uses_advanced_model_for_advanced_summary():
    resource = ModelResource(
        id="ollama",
        provider="ollama",
        model="normal-model",
        advanced_model="advanced-model",
    )
    router = ProfileModelRouter(
        ModelsConfig(
            resources=[resource],
            chat=ProfileRoute(priority=["ollama"]),
            summarize=ProfileRoute(priority=["ollama"]),
        )
    )

    async def complete(selected, prompt, *, json_mode, timeout, profile):
        assert selected.model == "advanced-model"
        return '{"ok":true}'

    with patch.object(router, "_ollama_complete", side_effect=complete):
        result = await router.complete(
            "summarize",
            profile="summarize",
            summary_tier="advanced",
            json_mode=True,
        )

    assert result == '{"ok":true}'
    assert router.last_model == "advanced-model"


def test_segment_summary_tier_defaults_and_updates(tmp_path):
    conn = init_db(tmp_path / "tier.db")
    books = BookRepo(conn)
    books.insert(
        id="book",
        title="Book",
        format="txt",
        file_path="/tmp/book.txt",
        status="unread",
    )
    segments = SegmentRepo(conn)
    segments.insert_many(
        [
            {
                "id": "segment",
                "book_id": "book",
                "idx": 0,
                "raw_text": "text",
            }
        ]
    )

    assert segments.get("segment")["summary_tier"] == "normal"
    segments.update_summary(
        "segment",
        summary_json="{}",
        label="label",
        summary_model="advanced-model",
        summary_tier="advanced",
    )
    assert segments.get("segment")["summary_tier"] == "advanced"
    assert segments.summary_tier_for_book("book") == "advanced"

    segments.reset_summary("segment", summary_tier="normal")
    reset = segments.get("segment")
    assert reset["summary_tier"] == "normal"
    assert reset["summary_json"] is None
    assert reset["summary_status"] == "pending"
