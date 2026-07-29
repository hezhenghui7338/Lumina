"""Provider routing for cursor / aiping / api_key validation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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
    cursor = ModelResource(id="cursor", provider="cursor", model="composer-2.5")
    router = _router(chat=[cursor])
    with pytest.raises(RuntimeError, match="优先级链全部失败"):
        await router.chat([{"role": "user", "content": "hi"}], profile="chat")


@pytest.mark.asyncio
async def test_cursor_chat_uses_sdk():
    cursor = ModelResource(
        id="cursor",
        provider="cursor",
        model="composer-2.5",
        api_key="cursor-test-key",
    )
    router = _router(chat=[cursor])
    fake_result = SimpleNamespace(status="finished", result='{"answer":"hello"}')
    mock_agent = MagicMock()
    mock_agent.prompt.return_value = fake_result

    with patch.dict(
        "sys.modules",
        {
            "cursor_sdk": MagicMock(
                Agent=mock_agent,
                AgentOptions=MagicMock(),
                LocalAgentOptions=MagicMock(),
            )
        },
    ):
        raw = await router.chat([{"role": "user", "content": "hi"}], profile="chat")

    assert raw == '{"answer":"hello"}'
    mock_agent.prompt.assert_called_once()
    assert router.last_resource_id == "cursor"


@pytest.mark.asyncio
async def test_cursor_stream_yields_single_chunk():
    cursor = ModelResource(
        id="cursor",
        provider="cursor",
        model="composer-2.5",
        api_key="cursor-test-key",
    )
    router = _router(chat=[cursor])
    fake_result = SimpleNamespace(status="finished", result="streamed answer")
    mock_agent = MagicMock()
    mock_agent.prompt.return_value = fake_result

    with patch.dict(
        "sys.modules",
        {
            "cursor_sdk": MagicMock(
                Agent=mock_agent,
                AgentOptions=MagicMock(),
                LocalAgentOptions=MagicMock(),
            )
        },
    ):
        stream = await router.chat(
            [{"role": "user", "content": "hi"}],
            profile="chat",
            stream=True,
        )
        chunks = [chunk async for chunk in stream]

    assert chunks == ["streamed answer"]


def test_format_chain_failure_cursor_sdk_hint():
    resources = [ModelResource(id="cursor", provider="cursor", model="composer-2.5")]
    msg = _format_chain_failure(
        resources,
        RuntimeError("cursor-sdk not installed; run: pip install cursor-sdk"),
    )
    assert "已尝试：cursor" in msg
    assert "cursor-sdk" in msg
    assert "Release 版不支持 Cursor provider" in msg


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

    async def fake_ollama_complete(resource, prompt, *, json_mode, timeout):
        seen_timeouts.append(timeout)
        return '{"sentences":["a"],"bullets":[{"label":"a","body":"body one with enough length here"},{"label":"b","body":"body two with enough length here"},{"label":"c","body":"body three with enough length here"}],"label":"标签","anchor":"段 1"}'

    with patch.object(router, "_ollama_complete", side_effect=fake_ollama_complete):
        await router.complete("summarize this", profile="summarize", json_mode=True)

    assert seen_timeouts == [120.0]


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
