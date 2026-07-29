"""Segment summarize prompt selection tests."""

from lumina_core.config import ModelResource, ModelsConfig, ProfileRoute
from lumina_core.models.router import ProfileModelRouter
from lumina_core.summarize.segment import (
    SUMMARY_PROMPT,
    SUMMARY_PROMPT_OLLAMA,
    _segment_prompt_settings,
)


def _router(*, summarize_priority: list[str]) -> ProfileModelRouter:
    resources = [
        ModelResource(
            id="ollama",
            provider="ollama",
            base_url="http://127.0.0.1:11434",
            model="qwen3.5:4b",
        ),
        ModelResource(
            id="openai",
            provider="openai",
            base_url="https://api.openai.com/v1",
            model="gpt-4o-mini",
            api_key="key",
        ),
    ]
    return ProfileModelRouter(
        ModelsConfig(
            resources=resources,
            chat=ProfileRoute(priority=["openai"]),
            summarize=ProfileRoute(priority=summarize_priority),
        )
    )


def test_segment_prompt_settings_ollama_primary():
    router = _router(summarize_priority=["ollama", "openai"])
    template, text_limit, retries, min_body, is_ollama = _segment_prompt_settings(router)
    assert template is SUMMARY_PROMPT_OLLAMA
    assert text_limit == 3000
    assert retries == 2
    assert min_body == 12
    assert is_ollama is True


def test_ollama_minimal_prompt_only_sentences_and_bullets():
    assert "notes" not in SUMMARY_PROMPT_OLLAMA
    assert "follow_ups" not in SUMMARY_PROMPT_OLLAMA
    assert "anchor" not in SUMMARY_PROMPT_OLLAMA
    assert "sentences" in SUMMARY_PROMPT_OLLAMA
    assert "bullets" in SUMMARY_PROMPT_OLLAMA


def test_segment_prompt_settings_cloud_primary():
    router = _router(summarize_priority=["openai"])
    template, text_limit, retries, min_body, is_ollama = _segment_prompt_settings(router)
    assert template is SUMMARY_PROMPT
    assert text_limit == 8000
    assert retries == 3
    assert min_body == 20
    assert is_ollama is False
