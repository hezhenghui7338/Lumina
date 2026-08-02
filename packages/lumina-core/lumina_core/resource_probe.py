"""Unified readiness probes for configured model resources."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

from lumina_core.config import ModelResource
from lumina_core.models.openai_compat import openai_compat_client_base, openai_compat_paths
from lumina_core.ollama_setup import check_ollama_status, is_local_base_url
from lumina_core.ollama_setup import recommended_tiers as ollama_recommended_tiers


_CLOUD_PROVIDERS = frozenset({"openai", "openrouter", "cursor", "aiping", "custom"})
_KEY_REQUIRED_PROVIDERS = frozenset({"openai", "openrouter", "cursor", "aiping", "custom"})


@dataclass
class ResourceProbeResult:
    resource_id: str
    provider: str
    ready: bool
    probe_ok: bool
    key_configured: bool
    model_ready: bool
    message: str = ""
    available_models: list[str] = field(default_factory=list)
    base_url: str = ""
    # Ollama-specific (optional for clients)
    installed: bool = False
    installed_models: list[str] = field(default_factory=list)
    recommended_tiers: list[dict[str, str]] = field(default_factory=ollama_recommended_tiers)
    ram_gb: str = ""
    skipped: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _key_configured(resource: ModelResource) -> bool:
    return bool((resource.api_key or "").strip())


def _model_configured(resource: ModelResource) -> bool:
    return bool((resource.model or "").strip())


async def probe_resource(resource: ModelResource) -> ResourceProbeResult:
    provider = (resource.provider or "").strip().lower()
    key_ok = _key_configured(resource)
    model_ok = _model_configured(resource)

    if provider == "ollama":
        return await _probe_ollama(resource)
    if provider in _CLOUD_PROVIDERS:
        return await _probe_openai_compatible(resource, key_ok=key_ok, model_ok=model_ok)

    return ResourceProbeResult(
        resource_id=resource.id,
        provider=provider,
        ready=False,
        probe_ok=False,
        key_configured=key_ok,
        model_ready=model_ok,
        message=f"未知 provider：{provider}",
        base_url=resource.base_url or "",
    )


async def _probe_ollama(resource: ModelResource) -> ResourceProbeResult:
    base_url = resource.base_url or "http://127.0.0.1:11434"
    status = await check_ollama_status(base_url, resource.model or None)
    model_ok = _model_configured(resource)
    ready = status.probe_ok and status.model_ready and model_ok
    message = status.message or status.probe_detail or ""
    if status.probe_ok and not status.model_ready:
        message = message or f"模型未下载（{status.selected_model or resource.model}）"
    elif not status.probe_ok and not message:
        message = status.probe_detail or "Ollama 服务不可达"
    if not model_ok:
        ready = False
        message = message or "未设置模型"

    return ResourceProbeResult(
        resource_id=resource.id,
        provider="ollama",
        ready=ready,
        probe_ok=status.probe_ok,
        key_configured=True,
        model_ready=status.model_ready and model_ok,
        message=message,
        available_models=status.installed_models,
        base_url=base_url,
        installed=status.installed,
        installed_models=status.installed_models,
        recommended_tiers=status.recommended_tiers,
        ram_gb=status.ram_gb,
        skipped=False,
    )


async def _probe_openai_compatible(
    resource: ModelResource,
    *,
    key_ok: bool,
    model_ok: bool,
) -> ResourceProbeResult:
    provider = resource.provider
    base_url = (resource.base_url or "").rstrip("/")
    if not base_url:
        return ResourceProbeResult(
            resource_id=resource.id,
            provider=provider,
            ready=False,
            probe_ok=False,
            key_configured=key_ok,
            model_ready=model_ok,
            message="Base URL 未配置",
            base_url="",
        )
    if provider in _KEY_REQUIRED_PROVIDERS and not key_ok:
        return ResourceProbeResult(
            resource_id=resource.id,
            provider=provider,
            ready=False,
            probe_ok=False,
            key_configured=False,
            model_ready=model_ok,
            message="API Key 未配置",
            base_url=base_url,
        )
    if not model_ok:
        return ResourceProbeResult(
            resource_id=resource.id,
            provider=provider,
            ready=False,
            probe_ok=False,
            key_configured=key_ok,
            model_ready=False,
            message="未设置模型",
            base_url=base_url,
        )

    headers: dict[str, str] = {}
    if key_ok:
        headers["Authorization"] = f"Bearer {resource.api_key}"
    if provider == "openrouter":
        headers["HTTP-Referer"] = "https://lumina.local"
        headers["X-Title"] = "Lumina"

    probe_ok = False
    message = ""
    available_models: list[str] = []
    models_path, _ = openai_compat_paths(base_url)

    try:
        async with httpx.AsyncClient(
            base_url=openai_compat_client_base(base_url),
            headers=headers,
            timeout=5.0,
            trust_env=not is_local_base_url(base_url),
        ) as client:
            resp = await client.get(models_path)
            if resp.status_code == 200:
                probe_ok = True
                payload = resp.json()
                raw = payload.get("data") or payload.get("models") or []
                for item in raw:
                    if isinstance(item, dict):
                        mid = item.get("id") or item.get("name") or ""
                        if mid:
                            available_models.append(str(mid))
                    elif isinstance(item, str) and item:
                        available_models.append(item)
                available_models = sorted(set(available_models))
            elif resp.status_code == 401:
                message = "API Key 无效或未授权"
            else:
                message = f"模型列表请求失败（HTTP {resp.status_code}）"
    except httpx.ConnectError:
        message = f"无法连接 {base_url}"
    except httpx.TimeoutException:
        message = f"连接 {base_url} 超时"
    except httpx.HTTPError as exc:
        message = f"探活失败：{type(exc).__name__}"

    ready = probe_ok and key_ok and model_ok
    if probe_ok and not message:
        message = "已连通"

    return ResourceProbeResult(
        resource_id=resource.id,
        provider=provider,
        ready=ready,
        probe_ok=probe_ok,
        key_configured=key_ok,
        model_ready=model_ok,
        message=message,
        available_models=available_models,
        base_url=base_url,
    )
