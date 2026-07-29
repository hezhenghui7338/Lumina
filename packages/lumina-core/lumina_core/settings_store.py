"""Runtime settings persistence."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from lumina_core.config import (
    ModelsConfig,
    Settings,
    apply_env_keys,
    is_legacy_models_format,
    load_models_config,
    migrate_legacy_models,
    normalize_models_raw,
)
from lumina_core.secrets_store import (
    apply_secrets_to_models,
    apply_secrets_to_settings,
    load_secrets,
)

API_KEY_MASK = "***"
_ROUTE_PROFILES = ("chat", "summarize", "translate")
WEB_SEARCH_PROVIDERS = frozenset({"ddgs", "tavily"})


def settings_path(data_dir: Path) -> Path:
    return data_dir / "config.json"


def models_path(data_dir: Path) -> Path:
    return data_dir / "models.json"


def normalize_web_search_provider(value: str | None) -> str:
    raw = (value or "ddgs").strip().lower() or "ddgs"
    return raw if raw in WEB_SEARCH_PROVIDERS else "ddgs"


def resolve_web_search_provider(provider: str | None, tavily_api_key: str | None) -> str:
    """Resolve explicit provider; tavily without key falls back to ddgs."""
    choice = normalize_web_search_provider(provider)
    if choice == "tavily" and not (tavily_api_key or "").strip():
        return "ddgs"
    return choice


def _apply_search_env(settings: Settings) -> Settings:
    settings.web_search_provider = normalize_web_search_provider(settings.web_search_provider)
    env_key = os.getenv("TAVILY_API_KEY") or os.getenv("LUMINA_TAVILY_API_KEY")
    if env_key and not settings.tavily_api_key:
        settings.tavily_api_key = env_key
    return settings


def load_settings(data_dir: Path) -> Settings:
    path = settings_path(data_dir)
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw.pop("web_search_enabled", None)  # migrated away
        raw["data_dir"] = str(data_dir)
        settings = Settings(**raw)
    else:
        settings = Settings(data_dir=data_dir)
    settings = apply_secrets_to_settings(settings, load_secrets(data_dir))
    return _apply_search_env(settings)


def save_settings(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    path = settings_path(settings.data_dir)
    payload = settings.model_dump(mode="json")
    payload.pop("tavily_api_key", None)  # never persist secrets
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def merge_tavily_api_key(incoming: str | None, existing: str | None) -> str | None:
    if incoming is None or incoming == "" or incoming == API_KEY_MASK:
        return existing
    return incoming


def settings_public_dict(settings: Settings) -> dict[str, Any]:
    return {
        "target_language": settings.target_language,
        "web_search_provider": normalize_web_search_provider(settings.web_search_provider),
        "tavily_api_key": API_KEY_MASK if settings.tavily_api_key else None,
    }


def _overlay_user_models(base: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    if is_legacy_models_format(raw):
        return migrate_legacy_models(raw, base=base)

    merged = dict(base)
    if isinstance(raw.get("resources"), list):
        by_id = {r["id"]: r for r in merged.get("resources", []) if isinstance(r, dict) and r.get("id")}
        for item in raw["resources"]:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            rid = str(item["id"]).strip().lower()
            existing = by_id.get(rid, {"id": rid})
            for field, value in item.items():
                if field == "api_key":
                    continue
                existing[field] = value
            by_id[rid] = existing
        merged["resources"] = list(by_id.values())

    for profile in _ROUTE_PROFILES:
        block = raw.get(profile)
        if isinstance(block, dict) and "priority" in block:
            merged[profile] = {"priority": list(block.get("priority") or [])}

    if isinstance(raw.get("job_concurrency"), dict):
        merged["job_concurrency"] = raw["job_concurrency"]

    return normalize_models_raw(merged)


def load_models(data_dir: Path) -> ModelsConfig:
    """Load bundled defaults, overlay user models.json (no secrets), then env keys."""
    base = load_models_config().model_dump()
    path = models_path(data_dir)
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8")) or {}
        base = _overlay_user_models(base, raw)
    cfg = ModelsConfig.model_validate(normalize_models_raw(base))
    cfg = apply_secrets_to_models(cfg, load_secrets(data_dir))
    return apply_env_keys(cfg)


def save_models(data_dir: Path, models: ModelsConfig) -> None:
    """Persist models without API keys (keys live in secrets.json / env / memory)."""
    data_dir.mkdir(parents=True, exist_ok=True)
    data = models.model_dump()
    for resource in data.get("resources") or []:
        resource["api_key"] = None
    path = models_path(data_dir)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def merge_incoming_models(incoming: ModelsConfig, existing: ModelsConfig) -> ModelsConfig:
    """Keep existing api_key when client sends mask / empty / null."""
    data = incoming.model_dump()
    existing_by_id = {r.id: r for r in existing.resources}
    for resource in data.get("resources") or []:
        rid = resource.get("id")
        if not rid:
            continue
        key = resource.get("api_key")
        if key is None or key == "" or key == API_KEY_MASK:
            resource["api_key"] = existing_by_id.get(rid).api_key if rid in existing_by_id else None
    return ModelsConfig.model_validate(data)


def models_to_dict(models: ModelsConfig, *, redact: bool = True) -> dict[str, Any]:
    data = models.model_dump()
    if redact:
        for resource in data.get("resources") or []:
            key = resource.get("api_key")
            resource["api_key"] = API_KEY_MASK if key else None
    return data
