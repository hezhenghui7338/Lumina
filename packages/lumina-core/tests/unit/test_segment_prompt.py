"""Segment summarize prompt selection tests."""

from lumina_core.config import (
    CLOUD_CHUNK_MAX,
    ModelResource,
    ModelsConfig,
    OLLAMA_CHUNK_MAX,
    OPENROUTER_CHUNK_MAX,
    ProfileRoute,
    load_prompts_config,
)
from lumina_core.models.router import ProfileModelRouter
from lumina_core.prompts_defaults import (
    DEFAULT_DOCUMENT,
    DEFAULT_ROLLUP,
    DEFAULT_SEGMENT as SUMMARY_PROMPT,
    DEFAULT_SEGMENT_CLOUD as SUMMARY_PROMPT_CLOUD,
    DEFAULT_SEGMENT_OLLAMA as SUMMARY_PROMPT_OLLAMA,
    DEFAULT_SEGMENT_QUALITY,
)
from lumina_core.summarize.segment import _format_base_prompt, _segment_prompt_settings


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
    assert text_limit == OLLAMA_CHUNK_MAX
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
    assert text_limit == CLOUD_CHUNK_MAX
    assert retries == 3
    assert min_body == 12
    assert text_only is True
    assert minimal is True


def test_segment_prompts_forbid_assistant_as_narrator():
    from lumina_core.summarize.segment import _CONTEXT_GUIDANCE

    for template in (SUMMARY_PROMPT, SUMMARY_PROMPT_OLLAMA, SUMMARY_PROMPT_CLOUD, DEFAULT_ROLLUP):
        assert "阅读助手" in template
        assert "我如何如何" in template
        assert "禁止改成「叙述者」" in template
        assert "第三方速读员" in template
    assert "禁止写成「叙述者」" in _CONTEXT_GUIDANCE
    assert "阅读助手" in _CONTEXT_GUIDANCE
    prompts = load_prompts_config()
    assert "写成阅读助手" in (prompts.segment_quality or "")
    assert "改写成「叙述者」" in (prompts.segment_quality or "")


def test_segment_prompts_require_output_language():
    from lumina_core.summarize.segment import _CONTEXT_GUIDANCE

    for template in (
        SUMMARY_PROMPT,
        SUMMARY_PROMPT_OLLAMA,
        SUMMARY_PROMPT_CLOUD,
        DEFAULT_ROLLUP,
        DEFAULT_DOCUMENT,
    ):
        assert "{target_language}" in template
        assert "禁止夹杂" in template
    assert "{target_language}" in DEFAULT_SEGMENT_QUALITY
    assert "{target_language}" in _CONTEXT_GUIDANCE
    prompts = load_prompts_config()
    assert "{target_language}" in (prompts.segment_quality or "")


def test_format_base_prompt_injects_display_language():
    prompt = _format_base_prompt(
        SUMMARY_PROMPT_OLLAMA,
        anchor_label="§第一章 · 段 1",
        text="主角离乡赴考。",
        text_only=True,
        target_language="zh-CN",
    )
    assert "简体中文" in prompt
    assert "{target_language}" not in prompt
    assert "主角离乡赴考。" in prompt

    english = _format_base_prompt(
        SUMMARY_PROMPT,
        anchor_label="§1",
        text="Hello",
        text_only=False,
        target_language="en-US",
    )
    assert "English" in english


def test_format_base_prompt_without_target_language_placeholder():
    prompt = _format_base_prompt(
        "只总结 {text}",
        anchor_label="§1",
        text="hello",
        text_only=True,
        target_language="ja-JP",
    )
    assert prompt == "只总结 hello"


def test_segment_prompt_settings_cloud_primary_openrouter():
    router = _router(summarize_priority=["openrouter", "ollama"])
    prompts = load_prompts_config()
    template, text_limit, _, _, text_only, minimal, _ = _segment_prompt_settings(router, prompts)
    assert template == (prompts.segment_cloud or prompts.segment)
    assert template == SUMMARY_PROMPT_CLOUD
    assert text_limit == OPENROUTER_CHUNK_MAX
    assert text_only is True
    assert minimal is True
