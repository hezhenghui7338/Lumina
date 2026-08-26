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
    default_data_dir,
    is_legacy_models_format,
    load_models_config,
    migrate_legacy_models,
    normalize_models_raw,
    normalize_segment_tier,
)
from lumina_core.prompts_store import (
    default_prompts,
    load_prompts,
    merge_prompts,
    prompts_to_dict,
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


def _apply_ocr_env(settings: Settings) -> Settings:
    base_url = os.getenv("LUMINA_OCR_CLOUD_BASE_URL")
    model = os.getenv("LUMINA_OCR_CLOUD_MODEL")
    api_key = os.getenv("LUMINA_OCR_CLOUD_API_KEY")
    timeout = os.getenv("LUMINA_OCR_CLOUD_TIMEOUT_SECONDS")
    if base_url:
        settings.ocr_cloud_base_url = base_url.strip()
    if model:
        settings.ocr_cloud_model = model.strip()
    if api_key:
        settings.ocr_cloud_api_key = api_key.strip()
    if timeout:
        settings.ocr_cloud_timeout_seconds = max(1.0, float(timeout))
    return settings


_SETTINGS_SKIP_PERSIST = frozenset(
    {
        "host",
        "port",
        "data_dir",
        "prompts",
        "tavily_api_key",
        "ocr_cloud_api_key",
    }
)


def load_settings(data_dir: Path) -> Settings:
    path = settings_path(data_dir)
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        for key in _SETTINGS_SKIP_PERSIST:
            raw.pop(key, None)
        raw["data_dir"] = str(data_dir)
        settings = Settings(**raw)
    else:
        settings = Settings(data_dir=data_dir)
    settings = apply_secrets_to_settings(settings, load_secrets(data_dir))
    settings = _apply_search_env(settings)
    settings = _apply_ocr_env(settings)
    settings.prompts = load_prompts(data_dir)
    return settings


def hydrate_startup_settings(settings: Settings | None = None) -> Settings:
    """Load persisted user prefs, then overlay CLI/test constructor fields."""
    if settings is None:
        return load_settings(default_data_dir())
    persisted = load_settings(settings.data_dir)
    overlay = {name: getattr(settings, name) for name in settings.model_fields_set}
    if not overlay:
        return persisted
    return persisted.model_copy(update=overlay)


def save_settings(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    path = settings_path(settings.data_dir)
    payload = settings.model_dump(mode="json")
    for key in _SETTINGS_SKIP_PERSIST:
        payload.pop(key, None)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def merge_tavily_api_key(incoming: str | None, existing: str | None) -> str | None:
    if incoming is None or incoming == "" or incoming == API_KEY_MASK:
        return existing
    return incoming


def merge_ocr_cloud_api_key(incoming: str | None, existing: str | None) -> str | None:
    if incoming is None or incoming == "" or incoming == API_KEY_MASK:
        return existing
    return incoming


def settings_public_dict(settings: Settings) -> dict[str, Any]:
    prompts = settings.prompts or load_prompts(settings.data_dir)
    return {
        "target_language": settings.target_language,
        "web_search_provider": normalize_web_search_provider(settings.web_search_provider),
        "web_search_enabled": bool(settings.web_search_enabled),
        "tavily_api_key": API_KEY_MASK if settings.tavily_api_key else None,
        "ocr_cloud_base_url": settings.ocr_cloud_base_url,
        "ocr_cloud_model": settings.ocr_cloud_model,
        "ocr_cloud_api_key": API_KEY_MASK if settings.ocr_cloud_api_key else None,
        "ocr_cloud_timeout_seconds": settings.ocr_cloud_timeout_seconds,
        "debug_mode": settings.debug_mode,
        "auto_start_summary": settings.auto_start_summary,
        "default_segment_tier": normalize_segment_tier(settings.default_segment_tier),
        "prompts": prompts_to_dict(prompts),
        "prompts_defaults": prompts_to_dict(default_prompts()),
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

    if isinstance(raw.get("tts"), dict):
        base_tts = dict(merged.get("tts") or {})
        incoming_tts = raw["tts"]
        if isinstance(incoming_tts.get("priority"), list):
            base_tts["priority"] = list(incoming_tts.get("priority") or [])
        for key in ("engine", "model", "voice", "speed"):
            if key in incoming_tts:
                base_tts[key] = incoming_tts[key]
        base_tts["engine"] = "system"
        merged["tts"] = base_tts

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
