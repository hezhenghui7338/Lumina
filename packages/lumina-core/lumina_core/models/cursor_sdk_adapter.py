"""Cursor Agent SDK adapter (cloud, no-repo) for ProfileModelRouter.

Release sidecars do not bundle cursor-sdk. The package is installed on demand into
``{data_dir}/vendor/cursor-sdk`` and loaded via ``sys.path``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CURSOR_SDK_PACKAGE = "cursor-sdk"
_VENDOR_REL = Path("vendor") / "cursor-sdk"

_TEXT_SYSTEM = (
    "You are a text-only assistant for the Lumina reading app. "
    "Reply with the requested content only. "
    "Do not edit files, run shell commands, browse the web, or call tools."
)
_JSON_SYSTEM = (
    _TEXT_SYSTEM
    + " Respond with a single JSON object only — no markdown fences, no commentary."
)

_install_lock = threading.Lock()
_install_state = {
    "status": "idle",  # idle | installing | ready | error
    "message": "",
    "progress": "",
}


@dataclass
class CursorSdkStatus:
    installed: bool
    importable: bool
    status: str
    message: str
    vendor_dir: str
    progress: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def vendor_dir(data_dir: Path) -> Path:
    return Path(data_dir) / _VENDOR_REL


def install_hint(*, frozen: bool | None = None) -> str:
    is_frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if is_frozen:
        return "请在设置中点击「下载 Cursor SDK」，或确保本机有可用的 Python 3 后再试。"
    return f"uv sync --extra cursor  # or: pip install {CURSOR_SDK_PACKAGE}"


def _ensure_vendor_on_path(data_dir: Path) -> Path:
    target = vendor_dir(data_dir)
    target.mkdir(parents=True, exist_ok=True)
    path = str(target.resolve())
    if path not in sys.path:
        sys.path.insert(0, path)
    return target


def sdk_importable(data_dir: Path | None = None) -> bool:
    if data_dir is not None:
        _ensure_vendor_on_path(data_dir)
    try:
        import cursor_sdk  # noqa: F401
    except ImportError:
        return False
    return True


def get_install_state(data_dir: Path) -> CursorSdkStatus:
    with _install_lock:
        status = str(_install_state["status"])
        message = str(_install_state["message"])
        progress = str(_install_state["progress"])
    importable = sdk_importable(data_dir)
    installed = importable or vendor_dir(data_dir).exists() and any(vendor_dir(data_dir).iterdir())
    if importable and status in ("idle", "ready"):
        status = "ready"
        message = message or "Cursor SDK 已就绪"
    elif status == "installing":
        pass
    elif not importable and status != "error":
        status = "idle"
        message = message or "未安装 Cursor SDK"
    return CursorSdkStatus(
        installed=bool(installed),
        importable=importable,
        status=status,
        message=message,
        vendor_dir=str(vendor_dir(data_dir)),
        progress=progress,
    )


def _set_install_state(*, status: str, message: str = "", progress: str = "") -> None:
    with _install_lock:
        _install_state["status"] = status
        _install_state["message"] = message
        _install_state["progress"] = progress


def reset_install_state_for_tests() -> None:
    """Test helper: clear module-level install progress."""
    _set_install_state(status="idle", message="", progress="")


def mark_installing() -> None:
    _set_install_state(status="installing", message="正在下载 Cursor SDK…", progress="starting")


def _python_for_pip() -> str:
    if not getattr(sys, "frozen", False):
        return sys.executable
    for candidate in ("python3", "python"):
        path = shutil.which(candidate)
        if path:
            return path
    raise RuntimeError(
        "当前安装包未内置 Cursor SDK，且未找到本机 Python 3，无法下载。"
        + install_hint(frozen=True)
    )


def install_cursor_sdk(data_dir: Path) -> CursorSdkStatus:
    """Blocking pip install into the vendor dir. Call from a worker thread."""
    target = vendor_dir(data_dir)
    target.mkdir(parents=True, exist_ok=True)
    _set_install_state(status="installing", message="正在下载 Cursor SDK…", progress="starting")
    try:
        python = _python_for_pip()
        cmd = [
            python,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--target",
            str(target),
            CURSOR_SDK_PACKAGE,
        ]
        logger.info("installing cursor-sdk: %s", " ".join(cmd))
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "PIP_DISABLE_PIP_VERSION_CHECK": "1"},
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "pip failed").strip()[:500]
            _set_install_state(status="error", message=f"下载失败：{detail}", progress="")
            return get_install_state(data_dir)
        _ensure_vendor_on_path(data_dir)
        if not sdk_importable(data_dir):
            _set_install_state(
                status="error",
                message="已下载但无法导入 cursor_sdk，请重试或检查依赖。",
                progress="",
            )
            return get_install_state(data_dir)
        _set_install_state(status="ready", message="Cursor SDK 已就绪", progress="done")
    except Exception as exc:  # noqa: BLE001 — surface to settings UI
        _set_install_state(status="error", message=f"下载失败：{exc}", progress="")
    return get_install_state(data_dir)


async def install_cursor_sdk_async(data_dir: Path) -> CursorSdkStatus:
    return await asyncio.to_thread(install_cursor_sdk, data_dir)


def require_sdk(data_dir: Path) -> None:
    if sdk_importable(data_dir):
        return
    raise RuntimeError(
        "cursor sdk not installed。"
        f"请在设置中下载 Cursor SDK（目标目录：{vendor_dir(data_dir)}）。"
        f" 开发环境也可：{install_hint()}"
    )


def _flatten_messages(
    messages: list[dict[str, str]],
    *,
    json_mode: bool,
) -> str:
    parts: list[str] = [_JSON_SYSTEM if json_mode else _TEXT_SYSTEM]
    for item in messages:
        role = (item.get("role") or "user").strip().lower()
        content = (item.get("content") or "").strip()
        if not content:
            continue
        if role == "system":
            parts.append(f"[system]\n{content}")
        elif role == "assistant":
            parts.append(f"[assistant]\n{content}")
        else:
            parts.append(f"[user]\n{content}")
    return "\n\n".join(parts)


def _result_text(result: Any) -> str:
    if result is None:
        return ""
    status = getattr(result, "status", None)
    if status == "error":
        raise RuntimeError(f"cursor run failed: {getattr(result, 'id', '') or result}")
    if status == "cancelled":
        raise RuntimeError("cursor run cancelled")
    text = getattr(result, "result", None)
    if isinstance(text, str) and text.strip():
        return text
    if isinstance(result, str):
        return result
    return str(text or "")


def _usage_from_result(result: Any) -> dict[str, int] | None:
    usage = getattr(result, "usage", None)
    if usage is None:
        return None
    prompt = getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", None)
    completion = getattr(usage, "output_tokens", None) or getattr(
        usage, "completion_tokens", None
    )
    total = getattr(usage, "total_tokens", None)
    out: dict[str, int] = {}
    if prompt is not None:
        out["prompt_tokens"] = int(prompt)
    if completion is not None:
        out["completion_tokens"] = int(completion)
    if total is not None:
        out["total_tokens"] = int(total)
    elif out.get("prompt_tokens") is not None and out.get("completion_tokens") is not None:
        out["total_tokens"] = out["prompt_tokens"] + out["completion_tokens"]
    return out or None


async def cursor_complete(
    *,
    data_dir: Path,
    api_key: str,
    model: str,
    prompt: str,
    json_mode: bool = False,
) -> tuple[str, dict[str, int] | None]:
    require_sdk(data_dir)
    messages = [{"role": "user", "content": prompt}]
    return await cursor_chat(
        data_dir=data_dir,
        api_key=api_key,
        model=model,
        messages=messages,
        json_mode=json_mode,
    )


async def cursor_chat(
    *,
    data_dir: Path,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    json_mode: bool = False,
) -> tuple[str, dict[str, int] | None]:
    require_sdk(data_dir)
    payload = _flatten_messages(messages, json_mode=json_mode)
    return await _run_cloud_prompt(
        api_key=api_key,
        model=model,
        message=payload,
    )


async def cursor_chat_stream(
    *,
    data_dir: Path,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    json_mode: bool = False,
) -> AsyncIterator[tuple[str, dict[str, int] | None]]:
    """Yield (text_chunk, usage_or_none). Final usage may arrive on the last empty chunk."""
    require_sdk(data_dir)
    payload = _flatten_messages(messages, json_mode=json_mode)
    async for item in _stream_cloud_prompt(
        api_key=api_key,
        model=model,
        message=payload,
    ):
        yield item


async def _run_cloud_prompt(
    *,
    api_key: str,
    model: str,
    message: str,
) -> tuple[str, dict[str, int] | None]:
    """Prefer AsyncAgent; fall back to sync Agent in a worker thread."""
    try:
        return await _run_cloud_prompt_async(api_key=api_key, model=model, message=message)
    except Exception as exc:
        logger.info("async cursor path unavailable (%s); using sync thread", exc)
        return await asyncio.to_thread(
            _run_cloud_prompt_sync,
            api_key=api_key,
            model=model,
            message=message,
        )


async def _run_cloud_prompt_async(
    *,
    api_key: str,
    model: str,
    message: str,
) -> tuple[str, dict[str, int] | None]:
    from cursor_sdk import AgentOptions, AsyncAgent, AsyncClient, CloudAgentOptions

    options = AgentOptions(
        model=model,
        api_key=api_key,
        cloud=CloudAgentOptions(repos=[]),
    )
    # Cloud-only: AsyncClient without local bridge when supported.
    client_cm = getattr(AsyncClient, "create", None)
    if client_cm is not None:
        async with await AsyncClient.create(api_key=api_key) as client:  # type: ignore[misc]
            result = await AsyncAgent.prompt(message, options, client=client)
            return _result_text(result), _usage_from_result(result)

    async with AsyncClient(api_key=api_key) as client:  # type: ignore[call-arg]
        result = await AsyncAgent.prompt(message, options, client=client)
        return _result_text(result), _usage_from_result(result)


def _run_cloud_prompt_sync(
    *,
    api_key: str,
    model: str,
    message: str,
) -> tuple[str, dict[str, int] | None]:
    from cursor_sdk import Agent, CloudAgentOptions

    with Agent.create(
        model=model,
        api_key=api_key,
        cloud=CloudAgentOptions(repos=[]),
    ) as agent:
        run = agent.send(message)
        result = run.wait()
        return _result_text(result), _usage_from_result(result) or _usage_from_result(run)


async def _stream_cloud_prompt(
    *,
    api_key: str,
    model: str,
    message: str,
) -> AsyncIterator[tuple[str, dict[str, int] | None]]:
    try:
        async for item in _stream_cloud_prompt_async(
            api_key=api_key, model=model, message=message
        ):
            yield item
        return
    except Exception as exc:
        logger.info("async cursor stream unavailable (%s); buffering sync result", exc)

    text, usage = await asyncio.to_thread(
        _run_cloud_prompt_sync,
        api_key=api_key,
        model=model,
        message=message,
    )
    if text:
        yield text, None
    yield "", usage


async def _stream_cloud_prompt_async(
    *,
    api_key: str,
    model: str,
    message: str,
) -> AsyncIterator[tuple[str, dict[str, int] | None]]:
    from cursor_sdk import AgentOptions, AsyncClient, CloudAgentOptions

    options = AgentOptions(
        model=model,
        api_key=api_key,
        cloud=CloudAgentOptions(repos=[]),
    )

    async def _open_client():
        if hasattr(AsyncClient, "create"):
            return await AsyncClient.create(api_key=api_key)  # type: ignore[misc]
        return AsyncClient(api_key=api_key)  # type: ignore[call-arg]

    client = await _open_client()
    try:
        agent = await client.agents.create(
            model=model,
            api_key=api_key,
            cloud=CloudAgentOptions(repos=[]),
        )
        try:
            run = await agent.send(message)
            if hasattr(run, "iter_text"):
                async for chunk in run.iter_text():
                    if chunk:
                        yield str(chunk), None
            elif hasattr(run, "stream"):
                async for event in run.stream():
                    text = _assistant_delta(event)
                    if text:
                        yield text, None
            result = await run.wait()
            yield "", _usage_from_result(result) or _usage_from_result(run)
            _ = options  # retained for API parity / future system options
        finally:
            close = getattr(agent, "close", None) or getattr(agent, "aclose", None)
            if close is not None:
                maybe = close()
                if asyncio.iscoroutine(maybe):
                    await maybe
    finally:
        close = getattr(client, "close", None) or getattr(client, "aclose", None)
        if close is not None:
            maybe = close()
            if asyncio.iscoroutine(maybe):
                await maybe


def _assistant_delta(event: Any) -> str:
    etype = getattr(event, "type", None)
    if etype == "assistant":
        message = getattr(event, "message", None)
        content = getattr(message, "content", None) if message is not None else None
        parts: list[str] = []
        if isinstance(content, list):
            for block in content:
                if getattr(block, "type", None) == "text":
                    parts.append(str(getattr(block, "text", "") or ""))
                elif isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text") or ""))
        return "".join(parts)
    if etype == "text":
        return str(getattr(event, "text", "") or "")
    return ""


async def list_cursor_models(api_key: str) -> list[str]:
    """Best-effort model catalog for probe; empty list on soft failure."""
    try:
        from cursor_sdk import Cursor

        def _list() -> list[str]:
            models = Cursor.models.list(api_key=api_key)
            out: list[str] = []
            for item in models or []:
                mid = getattr(item, "id", None)
                if mid:
                    out.append(str(mid))
            return sorted(set(out))

        return await asyncio.to_thread(_list)
    except Exception as exc:  # noqa: BLE001
        logger.debug("cursor models.list failed: %s", exc)
        return []
