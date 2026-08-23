"""Local secrets persistence (Application Support/secrets.json)."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from lumina_core.config import ModelsConfig, Settings

_KEY_MASK = "***"


def secrets_path(data_dir: Path) -> Path:
    return data_dir / "secrets.json"


@dataclass
class SecretsPayload:
    resources: dict[str, str] = field(default_factory=dict)
    tavily: str | None = None
    ocr_cloud: str | None = None


def load_secrets(data_dir: Path) -> SecretsPayload:
    path = secrets_path(data_dir)
    if not path.exists():
        return SecretsPayload()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return SecretsPayload()
    resources_raw = raw.get("resources") or {}
    if not isinstance(resources_raw, dict):
        resources_raw = {}
    resources = {
        str(rid): str(key)
        for rid, key in resources_raw.items()
        if key not in (None, "")
    }
    tavily_raw = raw.get("tavily")
    tavily = str(tavily_raw) if tavily_raw not in (None, "") else None
    ocr_cloud_raw = raw.get("ocr_cloud")
    ocr_cloud = str(ocr_cloud_raw) if ocr_cloud_raw not in (None, "") else None
    return SecretsPayload(resources=resources, tavily=tavily, ocr_cloud=ocr_cloud)


def save_secrets(data_dir: Path, payload: SecretsPayload) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = secrets_path(data_dir)
    data: dict[str, object] = {"resources": payload.resources}
    if payload.tavily:
        data["tavily"] = payload.tavily
    if payload.ocr_cloud:
        data["ocr_cloud"] = payload.ocr_cloud
    fd, tmp_path = tempfile.mkstemp(dir=data_dir, prefix=".secrets-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    os.chmod(path, 0o600)


def apply_secrets_to_models(models: ModelsConfig, secrets: SecretsPayload) -> ModelsConfig:
    if not secrets.resources:
        return models
    data = models.model_dump()
    for resource in data.get("resources") or []:
        rid = resource.get("id")
        if rid and rid in secrets.resources:
            resource["api_key"] = secrets.resources[rid]
    return ModelsConfig.model_validate(data)


def apply_secrets_to_settings(settings: Settings, secrets: SecretsPayload) -> Settings:
    if secrets.tavily and not settings.tavily_api_key:
        settings.tavily_api_key = secrets.tavily
    if secrets.ocr_cloud and not settings.ocr_cloud_api_key:
        settings.ocr_cloud_api_key = secrets.ocr_cloud
    return settings


def persist_secrets(data_dir: Path, models: ModelsConfig, settings: Settings) -> None:
    """Write current in-memory secrets to disk (0600)."""
    resources: dict[str, str] = {}
    for resource in models.resources:
        key = resource.api_key
        if key and key != _KEY_MASK:
            resources[resource.id] = key
    tavily = settings.tavily_api_key
    ocr_cloud = settings.ocr_cloud_api_key
    payload = SecretsPayload(
        resources=resources,
        tavily=tavily if tavily and tavily != _KEY_MASK else None,
        ocr_cloud=ocr_cloud if ocr_cloud and ocr_cloud != _KEY_MASK else None,
    )
    save_secrets(data_dir, payload)
