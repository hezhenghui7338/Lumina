"""Runtime settings persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lumina_core.config import ModelsConfig, Settings, apply_env_keys, load_models_config


def settings_path(data_dir: Path) -> Path:
    return data_dir / "config.json"


def load_settings(data_dir: Path) -> Settings:
    path = settings_path(data_dir)
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        return Settings(**raw)
    return Settings(data_dir=data_dir)


def save_settings(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    path = settings_path(settings.data_dir)
    payload = settings.model_dump(mode="json")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_models(data_dir: Path) -> ModelsConfig:
    return apply_env_keys(load_models_config())


def models_to_dict(models: ModelsConfig) -> dict[str, Any]:
    return models.model_dump()
