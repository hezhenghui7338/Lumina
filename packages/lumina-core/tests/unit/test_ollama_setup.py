"""Unit tests for Ollama status detection."""

from __future__ import annotations

import httpx
import pytest

from lumina_core.ollama_setup import (
    check_ollama_status,
    is_embedding_model,
    model_name_matches,
    pick_installed_chat_model,
    resolve_ollama_model,
)


@pytest.mark.parametrize(
    ("recommended", "name", "ok"),
    [
        ("qwen3.5:4b", "qwen3.5:4b", True),
        ("qwen3.5:4b", "qwen3.5:2b", False),
        ("qwen3.5:4b", "qwen3.5", False),
        ("llama3", "llama3:latest", True),
        ("llama3:latest", "llama3", True),
        ("llama3", "llama3", True),
    ],
)
def test_model_name_matches(recommended: str, name: str, ok: bool) -> None:
    assert model_name_matches(recommended, name) is ok


def test_is_embedding_model() -> None:
    assert is_embedding_model("bge-m3:latest") is True
    assert is_embedding_model("nomic-embed-text") is True
    assert is_embedding_model("llama3.2:3b") is False
    assert is_embedding_model("qwen3.5:4b") is False


def test_pick_prefers_ram_recommended_tier() -> None:
    # 16GB → recommend 4b; both 2b and 4b installed → 4b
    ram = 16 * (1024**3)
    picked = pick_installed_chat_model(
        ["qwen3.5:2b", "qwen3.5:4b", "bge-m3:latest"],
        ram_bytes=ram,
    )
    assert picked == "qwen3.5:4b"


def test_pick_closest_tier_when_recommended_missing() -> None:
    # 16GB → recommend 4b; only 2b and 9b installed → closest index is 2b (idx 1 vs 3)
    ram = 16 * (1024**3)
    picked = pick_installed_chat_model(["qwen3.5:2b", "qwen3.5:9b"], ram_bytes=ram)
    assert picked == "qwen3.5:2b"


def test_pick_falls_back_to_any_chat_model() -> None:
    picked = pick_installed_chat_model(
        ["bge-m3:latest", "llama3.2:3b"],
        ram_bytes=16 * (1024**3),
    )
    assert picked == "llama3.2:3b"


def test_pick_returns_none_when_only_embeddings() -> None:
    assert pick_installed_chat_model(["bge-m3:latest"], ram_bytes=16 * (1024**3)) is None


def test_resolve_keeps_configured_when_installed() -> None:
    model, adopted = resolve_ollama_model(
        "qwen3.5:4b",
        ["qwen3.5:4b", "llama3.2:3b"],
        ram_bytes=16 * (1024**3),
    )
    assert model == "qwen3.5:4b"
    assert adopted is False


def test_resolve_adopts_local_when_configured_missing() -> None:
    model, adopted = resolve_ollama_model(
        "qwen3.5:4b",
        ["llama3.2:3b", "bge-m3:latest"],
        ram_bytes=16 * (1024**3),
    )
    assert model == "llama3.2:3b"
    assert adopted is True


def test_resolve_keeps_configured_when_no_chat_models() -> None:
    model, adopted = resolve_ollama_model(
        "qwen3.5:4b",
        ["bge-m3:latest"],
        ram_bytes=16 * (1024**3),
    )
    assert model == "qwen3.5:4b"
    assert adopted is False


def _client_factory(handler):
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    return factory


def _boom_client(exc: BaseException):
    class BoomClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def get(self, path: str):
            raise exc

    return BoomClient


@pytest.mark.asyncio
async def test_served_when_path_missing_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(
        "lumina_core.ollama_setup._OLLAMA_CANDIDATES",
        ("/nonexistent/ollama",),
    )
    monkeypatch.setattr("lumina_core.ollama_setup.ollama_app_present", lambda: False)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(
            200,
            json={"models": [{"name": "qwen3.5:4b"}, {"name": "bge-m3:latest"}]},
        )

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))

    status = await check_ollama_status(model="qwen3.5:4b")
    assert status.installed is True
    assert status.served is True
    assert status.probe_ok is True
    assert status.model_ready is True
    assert status.message == ""
    assert status.probe_detail == ""
    assert status.base_url == "http://127.0.0.1:11434"
    assert status.selected_model == "qwen3.5:4b"
    assert status.installed_models == ["bge-m3:latest", "qwen3.5:4b"]
    assert any(t["model"] == "qwen3.5:4b" for t in status.recommended_tiers)
    assert {t["model"] for t in status.recommended_tiers} >= {
        "qwen3.5:0.8b",
        "qwen3.5:2b",
        "qwen3.5:4b",
        "qwen3.5:9b",
    }


@pytest.mark.asyncio
async def test_served_but_model_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(
        "lumina_core.ollama_setup._OLLAMA_CANDIDATES",
        ("/nonexistent/ollama",),
    )
    monkeypatch.setattr("lumina_core.ollama_setup.ollama_app_present", lambda: False)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "qwen3.5:2b"}]})

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))

    status = await check_ollama_status(model="qwen3.5:4b")
    assert status.installed is True
    assert status.served is True
    assert status.probe_ok is True
    assert status.model_ready is False
    assert status.selected_model == "qwen3.5:4b"
    assert status.installed_models == ["qwen3.5:2b"]
    assert "当前模型未下载" in status.message
    assert "qwen3.5:4b" in status.message
    assert "当前模型未下载" in status.probe_detail


@pytest.mark.asyncio
async def test_model_ready_follows_selected_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(
        "lumina_core.ollama_setup._OLLAMA_CANDIDATES",
        ("/nonexistent/ollama",),
    )
    monkeypatch.setattr("lumina_core.ollama_setup.ollama_app_present", lambda: False)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "qwen3.5:2b"}]})

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))

    missing = await check_ollama_status(model="qwen3.5:4b")
    assert missing.model_ready is False

    ready = await check_ollama_status(model="qwen3.5:2b")
    assert ready.model_ready is True
    assert ready.selected_model == "qwen3.5:2b"
    assert ready.model == "qwen3.5:2b"


@pytest.mark.asyncio
async def test_not_served_when_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(
        "lumina_core.ollama_setup._OLLAMA_CANDIDATES",
        ("/nonexistent/ollama",),
    )
    monkeypatch.setattr("lumina_core.ollama_setup.ollama_app_present", lambda: False)
    # Binary present so message distinguishes "not started" from "not installed".
    monkeypatch.setattr(
        "lumina_core.ollama_setup.ollama_bin",
        lambda: "/opt/homebrew/bin/ollama",
    )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        _boom_client(httpx.ConnectError("connection refused")),
    )

    status = await check_ollama_status(model="qwen3.5:4b")
    assert status.installed is True
    assert status.served is False
    assert status.probe_ok is False
    assert status.model_ready is False
    assert "连接被拒绝" in status.probe_detail
    assert "服务未响应" in status.message
    assert status.base_url == "http://127.0.0.1:11434"


@pytest.mark.asyncio
async def test_timeout_when_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "lumina_core.ollama_setup.ollama_bin",
        lambda: "/opt/homebrew/bin/ollama",
    )
    monkeypatch.setattr("lumina_core.ollama_setup.ollama_app_present", lambda: False)
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        _boom_client(httpx.ReadTimeout("timed out")),
    )

    status = await check_ollama_status(
        base_url="http://127.0.0.1:11434",
        model="qwen3.5:4b",
    )
    assert status.installed is True
    assert status.probe_ok is False
    assert "超时" in status.probe_detail
    assert "服务未响应" in status.message


@pytest.mark.asyncio
async def test_local_probe_disables_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    captured: dict[str, object] = {}
    real = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "qwen3.5:4b"}]})

    def factory(*args, **kwargs):
        captured.update(kwargs)
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)

    status = await check_ollama_status(model="qwen3.5:4b")
    assert captured.get("trust_env") is False
    assert status.probe_ok is True


@pytest.mark.asyncio
async def test_http_error_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "lumina_core.ollama_setup.ollama_bin",
        lambda: "/opt/homebrew/bin/ollama",
    )
    monkeypatch.setattr("lumina_core.ollama_setup.ollama_app_present", lambda: False)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))

    status = await check_ollama_status(model="qwen3.5:4b")
    assert status.probe_ok is False
    assert "HTTP 503" in status.probe_detail
    assert "服务未响应" in status.message


@pytest.mark.asyncio
async def test_not_installed_and_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(
        "lumina_core.ollama_setup._OLLAMA_CANDIDATES",
        ("/nonexistent/ollama",),
    )
    monkeypatch.setattr("lumina_core.ollama_setup.ollama_app_present", lambda: False)
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        _boom_client(httpx.ConnectError("connection refused")),
    )

    status = await check_ollama_status(model="qwen3.5:4b")
    assert status.installed is False
    assert status.probe_ok is False
    assert "未检测到本机 Ollama 安装" in status.message
    assert "连接被拒绝" in status.probe_detail


@pytest.mark.asyncio
async def test_installed_via_app_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(
        "lumina_core.ollama_setup._OLLAMA_CANDIDATES",
        ("/nonexistent/ollama",),
    )
    monkeypatch.setattr("lumina_core.ollama_setup.ollama_app_present", lambda: True)
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        _boom_client(httpx.ConnectError("connection refused")),
    )

    status = await check_ollama_status(model="qwen3.5:4b")
    assert status.installed is True
    assert status.probe_ok is False
    assert "服务未响应" in status.message
