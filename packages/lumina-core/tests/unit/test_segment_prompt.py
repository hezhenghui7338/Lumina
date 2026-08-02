"""Segment summarize prompt selection tests."""

from lumina_core.config import ModelResource, ModelsConfig, ProfileRoute, load_prompts_config
from lumina_core.models.router import ProfileModelRouter
from lumina_core.prompts_defaults import (
    DEFAULT_SEGMENT as SUMMARY_PROMPT,
    DEFAULT_SEGMENT_CLOUD as SUMMARY_PROMPT_CLOUD,
    DEFAULT_SEGMENT_OLLAMA as SUMMARY_PROMPT_OLLAMA,
)
from lumina_core.summarize.segment import _segment_prompt_settings


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
        ModelResource(
            id="openrouter",
            provider="openrouter",
            base_url="https://openrouter.ai/api/v1",
            model="openrouter/free",
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
    prompts = load_prompts_config()
    template, text_limit, retries, min_body, text_only, minimal, _ = _segment_prompt_settings(
        router, prompts
    )
    assert template == (prompts.segment_ollama or prompts.segment)
    assert template == SUMMARY_PROMPT_OLLAMA
    assert text_limit == 3000
    assert retries == 2
    assert min_body == 12
    assert text_only is True
    assert minimal is True


def test_ollama_minimal_prompt_includes_follow_ups():
    assert "notes" not in SUMMARY_PROMPT_OLLAMA
    assert "follow_ups" in SUMMARY_PROMPT_OLLAMA
    assert "anchor" not in SUMMARY_PROMPT_OLLAMA
    assert "sentences" in SUMMARY_PROMPT_OLLAMA
    assert "bullets" in SUMMARY_PROMPT_OLLAMA


def test_segment_prompt_settings_cloud_primary_openai():
    router = _router(summarize_priority=["openai"])
    prompts = load_prompts_config()
    template, text_limit, retries, min_body, text_only, minimal, _ = _segment_prompt_settings(
        router, prompts
    )
    assert template == (prompts.segment_cloud or prompts.segment)
    assert template == SUMMARY_PROMPT_CLOUD
    assert text_limit == 4800
    assert retries == 3
    assert min_body == 12
    assert text_only is True
    assert minimal is True


def test_segment_prompt_settings_cloud_primary_openrouter():
    router = _router(summarize_priority=["openrouter", "ollama"])
    prompts = load_prompts_config()
    template, text_limit, _, _, text_only, minimal, _ = _segment_prompt_settings(router, prompts)
    assert template == (prompts.segment_cloud or prompts.segment)
    assert template == SUMMARY_PROMPT_CLOUD
    assert text_limit == 4200
    assert text_only is True
    assert minimal is True
