"""Ollama setup — reference LocalAgent ollama_setup.py (subset)."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from lumina_core.hardware import (
    MODEL_TIERS,
    format_ram_gb,
    recommend_ollama_model,
    total_ram_bytes,
)

_DEFAULT_BASE_URL = "http://127.0.0.1:11434"

_OLLAMA_CANDIDATES = (
    "/opt/homebrew/bin/ollama",
    "/usr/local/bin/ollama",
    "/Applications/Ollama.app/Contents/Resources/ollama",
)

_OLLAMA_APP_PATH = "/Applications/Ollama.app"


def recommended_tiers() -> list[dict[str, str]]:
    return [
        {"model": t.model, "size_hint": t.size_hint, "label": t.label}
        for t in MODEL_TIERS
    ]


@dataclass(frozen=True)
class OllamaStatus:
    installed: bool
    served: bool
    model: str
    model_ready: bool
    ram_gb: str
    message: str = ""
    base_url: str = _DEFAULT_BASE_URL
    probe_ok: bool = False
    probe_detail: str = ""
    selected_model: str = ""
    recommended_tiers: list[dict[str, str]] = field(default_factory=recommended_tiers)
    installed_models: list[str] = field(default_factory=list)


def ollama_bin() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    for path in _OLLAMA_CANDIDATES:
        if os.access(path, os.X_OK):
            return path
    return None


def ollama_app_present() -> bool:
    return os.path.isdir(_OLLAMA_APP_PATH)


def is_ollama_installed() -> bool:
    return ollama_bin() is not None or ollama_app_present()


def model_name_matches(recommended: str, name: str) -> bool:
    """Exact tag match; allow only a `:latest` suffix difference."""
    if name == recommended:
        return True
    if name == f"{recommended}:latest" or recommended == f"{name}:latest":
        return True
    return False


_EMBEDDING_HINTS = (
    "embed",
    "bge-",
    "nomic-embed",
    "all-minilm",
    "mxbai-embed",
    "snowflake-arctic-embed",
)


def is_embedding_model(name: str) -> bool:
    lower = name.lower()
    return any(hint in lower for hint in _EMBEDDING_HINTS)


def is_local_base_url(url: str) -> bool:
    """True for loopback hosts; local Ollama must bypass system HTTP proxies."""
    host = (urlparse(url).hostname or "").lower()
    return host in ("127.0.0.1", "localhost", "::1")


def _find_installed_match(target: str, installed: list[str]) -> str | None:
    for name in installed:
        if model_name_matches(target, name):
            return name
    return None


def pick_installed_chat_model(
    installed: list[str],
    ram_bytes: int | None = None,
) -> str | None:
    """Pick a local chat model: RAM tier first, then any non-embedding install."""
    chat_models = sorted({n for n in installed if n and not is_embedding_model(n)})
    if not chat_models:
        return None

    ram = ram_bytes if ram_bytes is not None else total_ram_bytes()
    preferred = recommend_ollama_model(ram)
    matched = _find_installed_match(preferred, chat_models)
    if matched:
        return matched

    # Among installed MODEL_TIERS, pick closest to the RAM recommendation.
    tier_models = [t.model for t in MODEL_TIERS]
    installed_tiers: list[tuple[int, str]] = []
    for idx, tier_model in enumerate(tier_models):
        hit = _find_installed_match(tier_model, chat_models)
        if hit:
            installed_tiers.append((idx, hit))
    if installed_tiers:
        preferred_idx = next(
            (i for i, m in enumerate(tier_models) if m == preferred),
            len(tier_models) // 2,
        )
        installed_tiers.sort(key=lambda item: (abs(item[0] - preferred_idx), item[0]))
        return installed_tiers[0][1]

    return chat_models[0]


def resolve_ollama_model(
    configured: str,
    installed: list[str],
    ram_bytes: int | None = None,
) -> tuple[str, bool]:
    """Return (model, adopted). Prefer configured when present; else local chat model."""
    configured = (configured or "").strip()
    if configured and _find_installed_match(configured, installed):
        return configured, False
    picked = pick_installed_chat_model(installed, ram_bytes=ram_bytes)
    if picked:
        return picked, True
    return configured or recommend_ollama_model(ram_bytes), False


def _classify_probe_error(exc: BaseException, base_url: str) -> str:
    if isinstance(exc, httpx.ConnectError):
        return f"无法连接 {base_url}（连接被拒绝，通常是 Ollama 未启动）"
    if isinstance(exc, httpx.TimeoutException):
        return f"连接 {base_url} 超时"
    if isinstance(exc, httpx.InvalidURL):
        return f"探测地址无效：{base_url}"
    return f"无法连接 {base_url}（{type(exc).__name__}）"


async def check_ollama_status(
    base_url: str = _DEFAULT_BASE_URL,
    model: str | None = None,
) -> OllamaStatus:
    ram = total_ram_bytes()
    selected = model or recommend_ollama_model(ram)
    installed = is_ollama_installed()
    served = False
    model_ready = False
    message = ""
    probe_detail = ""
    installed_models: list[str] = []

    try:
        async with httpx.AsyncClient(
            base_url=base_url,
            timeout=5.0,
            trust_env=not is_local_base_url(base_url),
        ) as client:
            resp = await client.get("/api/tags")
            if resp.status_code == 200:
                served = True
                # GUI-installed Ollama may be serving even when not on PATH.
                installed = True
                raw_models = resp.json().get("models", [])
                installed_models = sorted(
                    {m.get("name", "") for m in raw_models if m.get("name")}
                )
                model_ready = any(model_name_matches(selected, n) for n in installed_models)
            else:
                probe_detail = f"Ollama 返回 HTTP {resp.status_code}"
    except httpx.HTTPError as exc:
        probe_detail = _classify_probe_error(exc, base_url)

    if served and model_ready:
        message = ""
        probe_detail = ""
    elif served and not model_ready:
        message = f"服务已连接，当前模型未下载（{selected}）"
        probe_detail = message
    elif not installed:
        message = "未检测到本机 Ollama 安装，且服务不可达"
        if probe_detail:
            message = f"{message}：{probe_detail}"
        else:
            probe_detail = message
    else:
        # Installed but not reachable.
        if not probe_detail:
            probe_detail = f"无法连接 {base_url}（服务未响应）"
        message = f"已安装，但服务未响应：{probe_detail}"

    return OllamaStatus(
        installed=installed,
        served=served,
        model=selected,
        model_ready=model_ready,
        ram_gb=format_ram_gb(ram),
        message=message,
        base_url=base_url,
        probe_ok=served,
        probe_detail=probe_detail,
        selected_model=selected,
        recommended_tiers=recommended_tiers(),
        installed_models=installed_models,
    )
