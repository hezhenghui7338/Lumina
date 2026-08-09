"""Secrets file persistence."""

from __future__ import annotations

import json
import os
import platform
from pathlib import Path

from lumina_core.config import ModelsConfig, Settings
from lumina_core.secrets_store import (
    SecretsPayload,
    load_secrets,
    persist_secrets,
    save_secrets,
    secrets_path,
)
from lumina_core.settings_store import (
    API_KEY_MASK,
    load_models,
    load_settings,
    merge_incoming_models,
    merge_tavily_api_key,
)


def test_save_and_load_secrets_roundtrip(tmp_path: Path):
    payload = SecretsPayload(
        resources={"openai": "sk-test", "openrouter": "or-key"},
        tavily="tvly-test",
    )
    save_secrets(tmp_path, payload)
    loaded = load_secrets(tmp_path)
    assert loaded.resources == payload.resources
    assert loaded.tavily == "tvly-test"
    # POSIX mode bits are not meaningful on Windows NTFS.
    if platform.system() != "Windows":
        assert oct(secrets_path(tmp_path).stat().st_mode & 0o777) == oct(0o600)


def test_load_secrets_missing_file(tmp_path: Path):
    assert load_secrets(tmp_path) == SecretsPayload()


def test_persist_secrets_writes_only_real_keys(tmp_path: Path):
    models = ModelsConfig()
    openai = models.resource_by_id("openai")
    assert openai is not None
    models = ModelsConfig(
        resources=[
            openai.model_copy(update={"api_key": "sk-live"}),
            *(r for r in models.resources if r.id != "openai"),
        ],
        chat=models.chat,
        summarize=models.summarize,
    )
    settings = Settings(data_dir=tmp_path, tavily_api_key="tvly-live")
    persist_secrets(tmp_path, models, settings)
    raw = json.loads(secrets_path(tmp_path).read_text(encoding="utf-8"))
    assert raw["resources"]["openai"] == "sk-live"
    assert raw["tavily"] == "tvly-live"


def test_persist_secrets_clears_removed_keys(tmp_path: Path):
    save_secrets(
        tmp_path,
        SecretsPayload(resources={"openai": "sk-old"}, tavily="tvly-old"),
    )
    models = ModelsConfig()
    settings = Settings(data_dir=tmp_path)
    persist_secrets(tmp_path, models, settings)
    loaded = load_secrets(tmp_path)
    assert loaded.resources == {}
    assert loaded.tavily is None


def test_load_models_applies_secrets_before_env(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("LUMINA_RESOURCE_OPENAI_API_KEY", raising=False)
    save_secrets(tmp_path, SecretsPayload(resources={"openai": "file-key"}))
    loaded = load_models(tmp_path)
    openai = loaded.resource_by_id("openai")
    assert openai is not None
    assert openai.api_key == "file-key"


def test_load_models_env_overrides_secrets(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LUMINA_RESOURCE_OPENROUTER_API_KEY", "env-or")
    save_secrets(tmp_path, SecretsPayload(resources={"openrouter": "file-or"}))
    loaded = load_models(tmp_path)
    openrouter = loaded.resource_by_id("openrouter")
    assert openrouter is not None
    assert openrouter.api_key == "env-or"


def test_load_settings_applies_tavily_secret(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("LUMINA_TAVILY_API_KEY", raising=False)
    save_secrets(tmp_path, SecretsPayload(tavily="tvly-from-file"))
    loaded = load_settings(tmp_path)
    assert loaded.tavily_api_key == "tvly-from-file"


def test_restart_simulation_keeps_resource_and_tavily_keys(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("LUMINA_RESOURCE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("LUMINA_TAVILY_API_KEY", raising=False)

    models = ModelsConfig()
    openai = models.resource_by_id("openai")
    assert openai is not None
    merged = ModelsConfig(
        resources=[
            openai.model_copy(update={"api_key": "sk-persist"}),
            *(r for r in models.resources if r.id != "openai"),
        ],
        chat=models.chat,
        summarize=models.summarize,
    )
    settings = Settings(data_dir=tmp_path, tavily_api_key="tvly-persist")
    persist_secrets(tmp_path, merged, settings)

    reloaded_models = load_models(tmp_path)
    reloaded_settings = load_settings(tmp_path)
    openai2 = reloaded_models.resource_by_id("openai")
    assert openai2 is not None
    assert openai2.api_key == "sk-persist"
    assert reloaded_settings.tavily_api_key == "tvly-persist"


def test_merge_incoming_models_mask_preserves_existing():
    existing = ModelsConfig()
    openai = existing.resource_by_id("openai")
    assert openai is not None
    existing = ModelsConfig(
        resources=[
            openai.model_copy(update={"api_key": "sk-keep"}),
            *(r for r in existing.resources if r.id != "openai"),
        ],
        chat=existing.chat,
        summarize=existing.summarize,
    )
    incoming = ModelsConfig(
        resources=[
            openai.model_copy(update={"api_key": API_KEY_MASK}),
            *(r for r in existing.resources if r.id != "openai"),
        ],
        chat=existing.chat,
        summarize=existing.summarize,
    )
    merged = merge_incoming_models(incoming, existing)
    kept = merged.resource_by_id("openai")
    assert kept is not None
    assert kept.api_key == "sk-keep"


def test_merge_tavily_api_key_mask_preserves_existing():
    assert merge_tavily_api_key(API_KEY_MASK, "tvly-keep") == "tvly-keep"
