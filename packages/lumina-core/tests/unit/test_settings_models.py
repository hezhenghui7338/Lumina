"""Models settings persistence and API key redaction."""

from __future__ import annotations

import json
from pathlib import Path

from lumina_core.config import (
    ModelResource,
    ModelsConfig,
    ProfileRoute,
    migrate_legacy_models,
)
from lumina_core.settings_store import (
    API_KEY_MASK,
    load_models,
    merge_incoming_models,
    models_path,
    models_to_dict,
    save_models,
)


def _models(
    *,
    chat_priority: list[str] | None = None,
    summarize_priority: list[str] | None = None,
    resource_overrides: dict[str, dict] | None = None,
) -> ModelsConfig:
    resources = [r.model_copy(deep=True) for r in ModelsConfig().resources]
    if resource_overrides:
        by_id = {r.id: r for r in resources}
        for rid, fields in resource_overrides.items():
            existing = by_id[rid]
            by_id[rid] = existing.model_copy(update=fields)
        resources = list(by_id.values())
    return ModelsConfig(
        resources=resources,
        chat=ProfileRoute(priority=chat_priority or ["openai", "ollama"]),
        summarize=ProfileRoute(priority=summarize_priority or ["ollama"]),
    )


def test_save_models_strips_api_keys(tmp_path: Path):
    models = _models(
        resource_overrides={
            "openai": {"api_key": "sk-secret"},
            "ollama": {"api_key": "local-secret"},
        }
    )
    save_models(tmp_path, models)
    raw = json.loads(models_path(tmp_path).read_text(encoding="utf-8"))
    openai = next(r for r in raw["resources"] if r["id"] == "openai")
    ollama = next(r for r in raw["resources"] if r["id"] == "ollama")
    assert openai["api_key"] is None
    assert ollama["api_key"] is None
    assert raw["chat"]["priority"] == ["openai", "ollama"]


def test_load_models_overlays_user_file(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("LUMINA_CHAT_API_KEY", raising=False)
    monkeypatch.delenv("LUMINA_SUMMARIZE_API_KEY", raising=False)
    save_models(
        tmp_path,
        _models(
            summarize_priority=["ollama"],
            resource_overrides={"ollama": {"model": "qwen3.5:9b"}},
        ),
    )
    path = models_path(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["resources"][0]["api_key"] = "disk-secret"
    path.write_text(json.dumps(data), encoding="utf-8")

    loaded = load_models(tmp_path)
    ollama = loaded.resource_by_id("ollama")
    assert ollama is not None
    assert ollama.model == "qwen3.5:9b"
    assert ollama.api_key is None


def test_load_models_applies_env_keys(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LUMINA_CHAT_API_KEY", "env-chat-key")
    save_models(tmp_path, _models())
    loaded = load_models(tmp_path)
    openai = loaded.resource_by_id("openai")
    assert openai is not None
    assert openai.api_key == "env-chat-key"


def test_load_models_cursor_applies_cursor_env_fallback(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("LUMINA_CHAT_API_KEY", raising=False)
    monkeypatch.setenv("CURSOR_API_KEY", "cursor-env-key")
    models = _models(chat_priority=["cursor"])
    save_models(tmp_path, models)
    loaded = load_models(tmp_path)
    cursor = loaded.resource_by_id("cursor")
    assert cursor is not None
    assert cursor.api_key == "cursor-env-key"


def test_load_models_resource_env_key(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LUMINA_RESOURCE_OPENROUTER_API_KEY", "or-env")
    save_models(tmp_path, _models())
    loaded = load_models(tmp_path)
    openrouter = loaded.resource_by_id("openrouter")
    assert openrouter is not None
    assert openrouter.api_key == "or-env"


def test_save_models_persists_providers(tmp_path: Path):
    models = _models(
        chat_priority=["cursor"],
        summarize_priority=["aiping"],
        resource_overrides={
            "cursor": {"api_key": "cursor-secret"},
            "aiping": {"api_key": "aiping-secret"},
        },
    )
    save_models(tmp_path, models)
    raw = json.loads(models_path(tmp_path).read_text(encoding="utf-8"))
    cursor = next(r for r in raw["resources"] if r["id"] == "cursor")
    aiping = next(r for r in raw["resources"] if r["id"] == "aiping")
    assert cursor["provider"] == "cursor"
    assert aiping["provider"] == "aiping"
    assert cursor["api_key"] is None


def test_models_to_dict_redacts_keys():
    models = _models(
        resource_overrides={
            "openai": {"api_key": "sk-live"},
            "ollama": {"api_key": None},
        }
    )
    data = models_to_dict(models)
    openai = next(r for r in data["resources"] if r["id"] == "openai")
    ollama = next(r for r in data["resources"] if r["id"] == "ollama")
    assert openai["api_key"] == API_KEY_MASK
    assert ollama["api_key"] is None


def test_merge_incoming_preserves_masked_keys():
    existing = _models(
        resource_overrides={"openai": {"api_key": "sk-keep", "model": "gpt-4o-mini"}}
    )
    incoming = _models(
        resource_overrides={"openai": {"api_key": API_KEY_MASK, "model": "gpt-4o"}}
    )
    merged = merge_incoming_models(incoming, existing)
    openai = merged.resource_by_id("openai")
    assert openai is not None
    assert openai.api_key == "sk-keep"
    assert openai.model == "gpt-4o"


def test_merge_incoming_accepts_new_key():
    existing = _models(resource_overrides={"openai": {"api_key": "old"}})
    incoming = _models(resource_overrides={"openai": {"api_key": "new-key"}})
    merged = merge_incoming_models(incoming, existing)
    openai = merged.resource_by_id("openai")
    assert openai is not None
    assert openai.api_key == "new-key"


def test_migrate_legacy_models_json():
    legacy = {
        "chat": {
            "provider": "openrouter",
            "model": "anthropic/claude-sonnet-4",
            "base_url": "https://openrouter.ai/api/v1",
        },
        "summarize": {
            "provider": "ollama",
            "model": "qwen3.5:9b",
            "base_url": "http://127.0.0.1:11434",
        },
    }
    migrated = migrate_legacy_models(legacy)
    assert migrated["chat"]["priority"] == ["openrouter"]
    assert migrated["summarize"]["priority"] == ["ollama"]
    ollama = next(r for r in migrated["resources"] if r["id"] == "ollama")
    assert ollama["model"] == "qwen3.5:9b"


def test_load_models_migrates_legacy_file(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("LUMINA_CHAT_API_KEY", raising=False)
    legacy = {
        "chat": {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "base_url": "https://api.openai.com/v1",
        },
        "summarize": {
            "provider": "ollama",
            "model": "qwen3.5:4b",
            "base_url": "http://127.0.0.1:11434",
        },
    }
    models_path(tmp_path).write_text(json.dumps(legacy), encoding="utf-8")
    loaded = load_models(tmp_path)
    assert loaded.chat.priority == ["openai"]
    assert loaded.summarize.priority == ["ollama"]


def test_save_settings_strips_tavily_key(tmp_path: Path):
    from lumina_core.config import Settings
    from lumina_core.settings_store import load_settings, save_settings, settings_path

    settings = Settings(
        data_dir=tmp_path,
        web_search_provider="tavily",
        tavily_api_key="tvly-secret",
    )
    save_settings(settings)
    raw = json.loads(settings_path(tmp_path).read_text(encoding="utf-8"))
    assert "tavily_api_key" not in raw
    assert raw["web_search_provider"] == "tavily"

    loaded = load_settings(tmp_path)
    assert loaded.web_search_provider == "tavily"
    assert loaded.tavily_api_key is None
