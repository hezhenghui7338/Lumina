"""Provider routing for cursor / aiping / api_key validation."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from lumina_core.config import ModelResource, ModelsConfig, ProfileRoute
from lumina_core.models.router import ProfileModelRouter, _format_chain_failure


def _router(
    *,
    chat: list[ModelResource] | None = None,
    summarize: list[ModelResource] | None = None,
) -> ProfileModelRouter:
    default_ollama = ModelResource(
        id="ollama",
        provider="ollama",
        base_url="http://127.0.0.1:11434",
        model="qwen3.5:4b",
    )
    default_openai = ModelResource(
        id="openai",
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        api_key="test-key",
    )
    chat_resources = chat or [default_openai]
    summarize_resources = summarize or [default_ollama]
    return ProfileModelRouter(
        ModelsConfig(
            resources=[*chat_resources, *summarize_resources],
            chat=ProfileRoute(priority=[r.id for r in chat_resources]),
            summarize=ProfileRoute(priority=[r.id for r in summarize_resources]),
        )
    )


@pytest.mark.asyncio
async def test_aiping_requires_api_key():
    aiping = ModelResource(
        id="aiping",
        provider="aiping",
        base_url="https://aiping.cn/api/v1",
        model="GLM-5.2",
    )
    router = _router(chat=[aiping])
    with pytest.raises(RuntimeError, match="优先级链全部失败"):
        await router.chat([{"role": "user", "content": "hi"}], profile="chat")


@pytest.mark.asyncio
async def test_cursor_requires_api_key():
    cursor = ModelResource(
        id="cursor",
        provider="cursor",
        base_url="https://cursor-proxy.example/v1",
        model="composer-2.5",
    )
    router = _router(chat=[cursor])
    with pytest.raises(RuntimeError, match="优先级链全部失败"):
        await router.chat([{"role": "user", "content": "hi"}], profile="chat")


@pytest.mark.asyncio
async def test_cursor_requires_base_url():
    cursor = ModelResource(
        id="cursor",
        provider="cursor",
        model="composer-2.5",
        api_key="cursor-test-key",
    )
    router = _router(chat=[cursor])
    with pytest.raises(RuntimeError, match="base_url not set"):
        await router.chat([{"role": "user", "content": "hi"}], profile="chat")


@pytest.mark.asyncio
async def test_cursor_chat_uses_openai_path():
    cursor = ModelResource(
        id="cursor",
        provider="cursor",
        base_url="https://cursor-proxy.example/v1",
        model="composer-2.5",
        api_key="cursor-test-key",
    )
    router = _router(chat=[cursor])

    async def fake_openai(resource, messages, *, json_mode, timeout):
        assert resource.id == "cursor"
        assert messages == [{"role": "user", "content": "hi"}]
        return '{"answer":"hello"}'

    with patch.object(router, "_openai_chat", side_effect=fake_openai):
        raw = await router.chat([{"role": "user", "content": "hi"}], profile="chat")

    assert raw == '{"answer":"hello"}'
    assert router.last_resource_id == "cursor"


@pytest.mark.asyncio
async def test_cursor_stream_uses_openai_path():
    cursor = ModelResource(
        id="cursor",
        provider="cursor",
        base_url="https://cursor-proxy.example/v1",
        model="composer-2.5",
        api_key="cursor-test-key",
    )
    router = _router(chat=[cursor])

    async def fake_stream(resource, messages, *, json_mode, timeout):
        yield "streamed "
        yield "answer"

    with patch.object(router, "_openai_chat_stream", side_effect=fake_stream):
        stream = await router.chat(
            [{"role": "user", "content": "hi"}],
            profile="chat",
            stream=True,
        )
        chunks = [chunk async for chunk in stream]

    assert chunks == ["streamed ", "answer"]


def test_format_chain_failure_cursor_base_url_hint():
    resources = [ModelResource(id="cursor", provider="cursor", model="composer-2.5")]
    msg = _format_chain_failure(
        resources,
        RuntimeError("cursor base_url not set"),
    )
    assert "已尝试：cursor" in msg
    assert "OpenAI 兼容 Base URL" in msg


def test_format_chain_failure_connect_error_hint():
    resources = [
        ModelResource(
            id="ollama",
            provider="ollama",
            base_url="http://127.0.0.1:11434",
            model="qwen3.5:4b",
        )
    ]
    msg = _format_chain_failure(resources, httpx.ConnectError("connection refused"))
    assert "Ollama 已启动" in msg


def test_ollama_payload_disables_thinking():
    router = _router()
    ollama = router.models.resource_by_id("ollama")
    assert ollama is not None
    payload = router._ollama_payload(
        ollama,
        [{"role": "user", "content": "hi"}],
        json_mode=False,
        stream=False,
    )
    assert payload["think"] is False
    assert payload["options"]["num_predict"] == 1024


def test_ollama_payload_includes_keep_alive():
    router = _router()
    ollama = router.models.resource_by_id("ollama")
    assert ollama is not None
    payload = router._ollama_payload(
        ollama,
        [{"role": "user", "content": "hi"}],
        json_mode=False,
        stream=False,
    )
    assert payload["keep_alive"] == "30m"


def test_ollama_payload_json_mode_uses_lower_num_predict():
    router = _router()
    ollama = router.models.resource_by_id("ollama")
    assert ollama is not None
    payload = router._ollama_payload(
        ollama,
        [{"role": "user", "content": "hi"}],
        json_mode=True,
        stream=False,
    )
    assert payload["options"]["num_predict"] == 768


def test_ollama_payload_summarize_json_uses_384_num_predict():
    router = _router()
    ollama = router.models.resource_by_id("ollama")
    assert ollama is not None
    payload = router._ollama_payload(
        ollama,
        [{"role": "user", "content": "hi"}],
        json_mode=True,
        stream=False,
        profile="summarize",
    )
    assert payload["format"] == "json"
    assert payload["options"]["num_predict"] == 384


@pytest.mark.asyncio
async def test_summarize_complete_uses_full_ollama_timeout():
    ollama = ModelResource(
        id="ollama",
        provider="ollama",
        base_url="http://127.0.0.1:11434",
        model="qwen3.5:4b",
        chat_timeout=12,
    )
    openrouter = ModelResource(
        id="openrouter",
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        model="anthropic/claude-sonnet-4",
        api_key="test-key",
    )
    router = _router(summarize=[ollama, openrouter])
    seen_timeouts: list[float] = []

    async def fake_ollama_complete(resource, prompt, *, json_mode, timeout, profile="summarize"):
        seen_timeouts.append(timeout)
        return '{"sentences":["a"],"bullets":[{"label":"a","body":"body one with enough length here"},{"label":"b","body":"body two with enough length here"},{"label":"c","body":"body three with enough length here"}],"label":"标签","anchor":"段 1"}'

    with patch.object(router, "_ollama_complete", side_effect=fake_ollama_complete):
        await router.complete("summarize this", profile="summarize", json_mode=True)

    assert seen_timeouts == [180.0]


@pytest.mark.asyncio
async def test_chat_fallback_to_second_resource():
    failing = ModelResource(
        id="openai",
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        api_key="key",
    )
    ollama = ModelResource(
        id="ollama",
        provider="ollama",
        base_url="http://127.0.0.1:11434",
        model="qwen3.5:4b",
    )
    router = _router(chat=[failing, ollama])

    async def fake_openai(*args, **kwargs):
        raise httpx.TimeoutException("timeout")

    async def fake_ollama(resource, messages, *, json_mode, timeout):
        return "ollama-answer"

    with patch.object(router, "_openai_chat", side_effect=fake_openai):
        with patch.object(router, "_ollama_chat", side_effect=fake_ollama):
            text = await router.chat([{"role": "user", "content": "hi"}], profile="chat")

    assert text == "ollama-answer"
    assert router.last_resource_id == "ollama"
