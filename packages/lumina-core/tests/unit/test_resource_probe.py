"""Unit tests for unified resource readiness probes."""

from __future__ import annotations

import httpx
import pytest

from lumina_core.config import ModelResource, Settings
from lumina_core.resource_probe import probe_ocr, probe_resource


def _client_factory(handler):
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    return factory


@pytest.mark.asyncio
async def test_ocr_probe_uses_local_when_cloud_is_empty(monkeypatch) -> None:
    monkeypatch.setattr("lumina_core.resource_probe.ocr_dependency_warning", lambda: None)
    status = await probe_ocr(Settings())
    assert status.provider == "local"
    assert status.ready is True
    assert status.configured is False


@pytest.mark.asyncio
async def test_ocr_probe_reports_partial_cloud_configuration() -> None:
    status = await probe_ocr(Settings(ocr_cloud_base_url="https://example.test/v1"))
    assert status.provider == "cloud"
    assert status.ready is False
    assert "配置不完整" in status.message


@pytest.mark.asyncio
async def test_ocr_probe_checks_openai_compatible_models(monkeypatch) -> None:
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        _client_factory(lambda _request: httpx.Response(200, json={"data": [{"id": "vision"}]})),
    )
    status = await probe_ocr(
        Settings(
            ocr_cloud_base_url="https://example.test/v1",
            ocr_cloud_model="vision",
            ocr_cloud_api_key="secret",
        )
    )
    assert status.provider == "cloud"
    assert status.configured is True
    assert status.ready is True


@pytest.mark.asyncio
async def test_openai_probe_ready(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")
        assert request.headers.get("Authorization") == "Bearer sk-test"
        return httpx.Response(200, json={"data": [{"id": "gpt-4o-mini"}]})

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    resource = ModelResource(
        id="openai",
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        api_key="sk-test",
    )
    status = await probe_resource(resource)
    assert status.probe_ok is True
    assert status.ready is True
    assert status.key_configured is True
    assert "gpt-4o-mini" in status.available_models


@pytest.mark.asyncio
async def test_openai_probe_missing_key() -> None:
    resource = ModelResource(
        id="openai",
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        api_key=None,
    )
    status = await probe_resource(resource)
    assert status.ready is False
    assert status.probe_ok is False
    assert status.key_configured is False
    assert "Key" in status.message


@pytest.mark.asyncio
async def test_openai_probe_unauthorized(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid key"})

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    resource = ModelResource(
        id="openai",
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        api_key="bad-key",
    )
    status = await probe_resource(resource)
    assert status.probe_ok is False
    assert status.ready is False
    assert "无效" in status.message or "401" in status.message


@pytest.mark.asyncio
async def test_ollama_probe_without_chain_gate(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "qwen3.5:4b"}]})

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    resource = ModelResource(
        id="local-ollama",
        provider="ollama",
        base_url="http://127.0.0.1:11434",
        model="qwen3.5:4b",
    )
    status = await probe_resource(resource)
    assert status.skipped is False
    assert status.probe_ok is True
    assert status.model_ready is True
    assert status.ready is True


@pytest.mark.asyncio
async def test_cursor_probe_missing_base_url() -> None:
    resource = ModelResource(
        id="cursor",
        provider="cursor",
        base_url="",
        model="composer-2.5",
        api_key="cursor-key",
    )
    status = await probe_resource(resource)
    assert status.ready is False
    assert status.probe_ok is False
    assert "Base URL" in status.message


@pytest.mark.asyncio
async def test_cursor_probe_ready(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")
        assert request.headers.get("Authorization") == "Bearer cursor-key"
        return httpx.Response(200, json={"data": [{"id": "composer-2.5"}]})

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    resource = ModelResource(
        id="cursor",
        provider="cursor",
        base_url="https://cursor-proxy.example/v1",
        model="composer-2.5",
        api_key="cursor-key",
    )
    status = await probe_resource(resource)
    assert status.ready is True
    assert status.probe_ok is True
    assert status.key_configured is True
    assert "composer-2.5" in status.available_models


@pytest.mark.asyncio
async def test_cursor_probe_missing_key() -> None:
    resource = ModelResource(
        id="cursor",
        provider="cursor",
        base_url="https://cursor-proxy.example/v1",
        model="composer-2.5",
        api_key=None,
    )
    status = await probe_resource(resource)
    assert status.ready is False
    assert "Key" in status.message
