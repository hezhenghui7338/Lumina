"""Runtime configuration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

CHUNKER_VERSION = "1"
MAX_FILE_BYTES = 500 * 1024 * 1024  # 500MB
SHORT_BOOK_CHARS = 12_000
SHORT_BOOK_MAX_CHARS = SHORT_BOOK_CHARS
READING_TARGET_CHARS = 4000
CHUNK_TARGET_CHARS = READING_TARGET_CHARS
READING_HARD_MAX = 6000
CHUNK_MAX_CHARS = READING_HARD_MAX
CHUNK_MIN_CHARS = int(READING_TARGET_CHARS * 0.6)
SEGMENT_CACHE_QUOTA_BYTES = 2 * 1024 * 1024 * 1024  # 2GB
MAX_SUMMARY_RETRIES = 3
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
LUMINA_SUMMARIZE_MODEL = os.getenv("LUMINA_SUMMARIZE_MODEL", "qwen3.5:4b")


class ProfileConfig(BaseModel):
    provider: str = "ollama"
    model: str = "qwen3.5:4b"
    base_url: str = "http://localhost:11434"
    api_key: str | None = None


class JobConcurrency(BaseModel):
    ocr: int = 1
    segment: int = 1
    ollama: int = 1
    cloud: int = 4


class ModelsConfig(BaseModel):
    chat: ProfileConfig = Field(default_factory=ProfileConfig)
    summarize: ProfileConfig = Field(default_factory=ProfileConfig)
    translate: ProfileConfig = Field(default_factory=ProfileConfig)
    job_concurrency: JobConcurrency = Field(default_factory=JobConcurrency)


class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 17432
    data_dir: Path = Field(
        default_factory=lambda: Path.home() / "Library/Application Support/Lumina"
    )
    target_language: str = "zh-CN"
    web_search_enabled: bool = True

    class Config:
        env_prefix = "LUMINA_"


def default_data_dir() -> Path:
    override = os.getenv("LUMINA_DATA_DIR")
    if override:
        return Path(override)
    return Path.home() / "Library/Application Support/Lumina"


def bundle_root() -> Path | None:
    """Directory next to frozen lumina-core executable (PyInstaller one-folder)."""
    import sys

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return None


def load_models_config(path: Path | None = None) -> ModelsConfig:
    if path is None:
        root = bundle_root()
        if root is not None:
            path = root / "config" / "models.yaml"
        else:
            path = Path(__file__).resolve().parents[1] / "config" / "models.yaml"
    if not path.exists():
        return ModelsConfig()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return ModelsConfig.model_validate(raw)


def apply_env_keys(cfg: ModelsConfig) -> ModelsConfig:
    data = cfg.model_dump()
    for profile in ("chat", "summarize", "translate"):
        key = os.getenv(f"LUMINA_{profile.upper()}_API_KEY")
        if key:
            data[profile]["api_key"] = key
    return ModelsConfig.model_validate(data)
