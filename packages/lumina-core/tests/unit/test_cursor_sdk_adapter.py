"""Cursor SDK adapter: install status, message flatten, router wiring."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from lumina_core.config import ModelResource, ModelsConfig, ProfileRoute
from lumina_core.models import cursor_sdk_adapter
from lumina_core.models.router import ProfileModelRouter, _format_chain_failure


def test_flatten_messages_json_mode():
    text = cursor_sdk_adapter._flatten_messages(
        [
            {"role": "system", "content": "be careful"},
            {"role": "user", "content": "summarize"},
        ],
        json_mode=True,
    )
    assert "JSON object" in text
    assert "[system]" in text
    assert "[user]" in text
    assert "summarize" in text


def test_get_install_state_missing(tmp_path: Path):
    status = cursor_sdk_adapter.get_install_state(tmp_path)
    assert status.importable is False
    assert status.status in ("idle", "error", "ready")
    assert "vendor" in status.vendor_dir


def test_require_sdk_raises(tmp_path: Path):
    with patch.object(cursor_sdk_adapter, "sdk_importable", return_value=False):
        with pytest.raises(RuntimeError, match="sdk not installed"):
            cursor_sdk_adapter.require_sdk(tmp_path)


@pytest.mark.asyncio
async def test_cursor_complete_no_base_url_required(tmp_path: Path):
    cursor = ModelResource(
        id="cursor",
        provider="cursor",
        model="composer-2.5",
        api_key="cursor-test-key",
    )
    router = ProfileModelRouter(
        ModelsConfig(
            resources=[cursor],
            chat=ProfileRoute(priority=["cursor"]),
            summarize=ProfileRoute(priority=["cursor"]),
        ),
        data_dir=tmp_path,
    )

    async def fake_complete(*, data_dir, api_key, model, prompt, json_mode=False):
        assert data_dir == tmp_path
        assert api_key == "cursor-test-key"
        assert model == "composer-2.5"
        assert prompt == "hello"
        assert json_mode is True
        return '{"ok":true}', {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}

    with patch("lumina_core.models.router.cursor_complete", side_effect=fake_complete):
        text = await router.complete("hello", profile="summarize", json_mode=True)

    assert text == '{"ok":true}'
    assert router.last_resource_id == "cursor"
    assert router.last_usage == {
        "prompt_tokens": 1,
        "completion_tokens": 2,
        "total_tokens": 3,
    }


@pytest.mark.asyncio
async def test_cursor_chat_and_stream(tmp_path: Path):
    cursor = ModelResource(
        id="cursor",
        provider="cursor",
        model="composer-2.5",
        api_key="k",
    )
    router = ProfileModelRouter(
        ModelsConfig(
            resources=[cursor],
            chat=ProfileRoute(priority=["cursor"]),
            summarize=ProfileRoute(priority=["cursor"]),
        ),
        data_dir=tmp_path,
    )

    async def fake_chat(*, data_dir, api_key, model, messages, json_mode=False):
        return '{"answer":"hi"}', None

    async def fake_stream(*, data_dir, api_key, model, messages, json_mode=False):
        yield "a", None
        yield "b", {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4}

    with patch("lumina_core.models.router.cursor_chat", side_effect=fake_chat):
        raw = await router.chat([{"role": "user", "content": "hi"}], profile="chat")
    assert raw == '{"answer":"hi"}'

    with patch("lumina_core.models.router.cursor_chat_stream", side_effect=fake_stream):
        stream = await router.chat(
            [{"role": "user", "content": "hi"}],
            profile="chat",
            stream=True,
        )
        chunks = [c async for c in stream]
    assert chunks == ["a", "b"]
    assert router.last_usage == {
        "prompt_tokens": 2,
        "completion_tokens": 2,
        "total_tokens": 4,
    }


@pytest.mark.asyncio
async def test_cursor_requires_api_key_not_base_url(tmp_path: Path):
    cursor = ModelResource(
        id="cursor",
        provider="cursor",
        model="composer-2.5",
    )
    router = ProfileModelRouter(
        ModelsConfig(
            resources=[cursor],
            chat=ProfileRoute(priority=["cursor"]),
            summarize=ProfileRoute(priority=["cursor"]),
        ),
        data_dir=tmp_path,
    )
    with pytest.raises(RuntimeError, match="优先级链全部失败"):
        await router.chat([{"role": "user", "content": "hi"}], profile="chat")


def test_format_chain_failure_cursor_sdk_hint():
    resources = [ModelResource(id="cursor", provider="cursor", model="composer-2.5")]
    msg = _format_chain_failure(
        resources,
        RuntimeError("cursor sdk not installed"),
    )
    assert "下载 Cursor SDK" in msg


def test_format_chain_failure_legacy_base_url_hint():
    resources = [ModelResource(id="cursor", provider="cursor", model="composer-2.5")]
    msg = _format_chain_failure(
        resources,
        RuntimeError("cursor base_url not set"),
    )
    assert "官方 SDK" in msg
    assert "无需 Base URL" in msg


@pytest.mark.asyncio
async def test_install_sets_error_without_python(tmp_path: Path, monkeypatch):
    cursor_sdk_adapter.reset_install_state_for_tests()
    monkeypatch.setattr(cursor_sdk_adapter, "_python_for_pip", lambda: (_ for _ in ()).throw(RuntimeError("no py")))
    status = await cursor_sdk_adapter.install_cursor_sdk_async(tmp_path)
    assert status.status == "error"
    assert "失败" in status.message or "no py" in status.message
    cursor_sdk_adapter.reset_install_state_for_tests()
