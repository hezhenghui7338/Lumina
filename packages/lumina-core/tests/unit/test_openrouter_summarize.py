"""OpenRouter summarize integration tests (mocked HTTP)."""

from __future__ import annotations

import json as json_module
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from lumina_core.config import ModelResource, ModelsConfig, ProfileRoute
from lumina_core.models.router import ProfileModelRouter
from lumina_core.summarize.segment import summarize_segment

_VALID_SUMMARY = {
    "sentences": ["本段交代主角寒门出身与赴考之志。"],
    "bullets": [
        {"label": "寒门出身", "body": "主角生于贫苦农家，父亲早逝，母亲靠纺织维生。"},
        {"label": "赴考之志", "body": "段末以誓要金榜题名收束，将个人命运与科举制度绑定。"},
        {"label": "邻里关系", "body": "邻里虽敬其向学，却无力资助书卷。"},
    ],
}


def _openrouter_router() -> ProfileModelRouter:
    openrouter = ModelResource(
        id="openrouter",
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        model="openrouter/free",
        api_key="test-key",
    )
    return ProfileModelRouter(
        ModelsConfig(
            resources=[openrouter],
            chat=ProfileRoute(priority=["openrouter"]),
            summarize=ProfileRoute(priority=["openrouter"]),
        )
    )


@pytest.mark.asyncio
async def test_openrouter_json_format_400_retries_without_response_format():
    router = _openrouter_router()
    calls: list[dict] = []

    async def fake_post(path: str, *, json: dict) -> httpx.Response:
        calls.append(json)
        if "response_format" in json:
            request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
            return httpx.Response(400, request=request, text='{"error":"unsupported response_format"}')
        request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        body = {
            "choices": [
                {"message": {"content": json_module.dumps(_VALID_SUMMARY, ensure_ascii=False)}}
            ]
        }
        return httpx.Response(200, request=request, json=body)

    client = AsyncMock()
    client.post = fake_post
    with patch.object(router, "_client_for", return_value=client):
        result = await summarize_segment(
            router,
            raw_text="测试段落内容。" * 20,
            anchor_label="§第一章 · 段 1",
        )

    assert result.summary.label
    assert len(calls) == 2
    assert "response_format" in calls[0]
    assert calls[0].get("provider") == {"require_parameters": True}
    assert "response_format" not in calls[1]


@pytest.mark.asyncio
async def test_openrouter_complete_uses_correct_url():
    router = _openrouter_router()
    seen_urls: list[str] = []

    async def fake_post(path: str, *, json: dict) -> httpx.Response:
        seen_urls.append(path)
        request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        body = {
            "choices": [
                {"message": {"content": json_module.dumps(_VALID_SUMMARY, ensure_ascii=False)}}
            ]
        }
        return httpx.Response(200, request=request, json=body)

    client = AsyncMock()
    client.post = fake_post
    with patch.object(router, "_client_for", return_value=client):
        await router.complete("hello", profile="summarize", json_mode=True)

    assert seen_urls == ["chat/completions"]
