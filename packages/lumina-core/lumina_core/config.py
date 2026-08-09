"""Runtime configuration."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings

CHUNKER_VERSION = "4"
MAX_FILE_BYTES = 500 * 1024 * 1024  # 500MB
SHORT_BOOK_CHARS = 12_000
SHORT_BOOK_MAX_CHARS = SHORT_BOOK_CHARS
READING_TARGET_CHARS = 4000
CHUNK_TARGET_CHARS = READING_TARGET_CHARS
READING_HARD_MAX = 6000
CHUNK_MAX_CHARS = READING_HARD_MAX
CHUNK_MIN_CHARS = int(READING_TARGET_CHARS * 0.6)
OLLAMA_CHUNK_TARGET = 2500
OLLAMA_CHUNK_MAX = 3000
OPENROUTER_CHUNK_TARGET = 3500
OPENROUTER_CHUNK_MAX = 4200
OLLAMA_KEEP_ALIVE = os.getenv("LUMINA_OLLAMA_KEEP_ALIVE", "30m")
CLOUD_CHUNK_TARGET = 4000
CLOUD_CHUNK_MAX = 4800
SEGMENT_CACHE_QUOTA_BYTES = 2 * 1024 * 1024 * 1024  # 2GB
MAX_SUMMARY_RETRIES = 3
OLLAMA_SUMMARY_MAX_RETRIES = 2
SUMMARY_JOB_MAX_RETRIES = 2
OLLAMA_SUMMARY_MIN_BODY_CHARS = 12
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
LUMINA_SUMMARIZE_MODEL = os.getenv("LUMINA_SUMMARIZE_MODEL", "qwen3.5:4b")

# News / document summarize
SUMMARIZE_SHORT_MAX_CHARS = int(os.getenv("LUMINA_SUMMARIZE_SHORT_MAX_CHARS", "12000"))
SUMMARIZE_LLM_INPUT_CHARS = int(os.getenv("LUMINA_SUMMARIZE_LLM_INPUT_CHARS", "14000"))
NEWS_FETCH_MIN_CHARS = int(os.getenv("LUMINA_NEWS_FETCH_MIN_CHARS", "500"))
NEWS_FETCH_USE_JINA = os.getenv("LUMINA_NEWS_FETCH_USE_JINA", "1").lower() in (
    "1",
    "true",
    "yes",
)

_BUILTIN_RESOURCE_IDS = frozenset({"ollama", "openai", "openrouter", "cursor", "aiping"})


def _env_bool(name: str, default: str) -> bool:
    return os.getenv(name, default).lower() in ("1", "true", "yes")


def _env_float(name: str, default: str) -> float:
    return float(os.getenv(name, default))


def _env_int(name: str, default: str) -> int:
    return int(os.getenv(name, default))


SUMMARY_SEGMENT_TIMEOUT_SECONDS = _env_int("LUMINA_SUMMARY_SEGMENT_TIMEOUT", "180")
RELEASE_LIVE_MAX_RETRIES = _env_int("LUMINA_RELEASE_LIVE_MAX_RETRIES", "1")
RELEASE_LIVE_TIMEOUT_SECONDS = _env_int("LUMINA_RELEASE_LIVE_TIMEOUT", "150")


# OCR (scanned PDF; optional lumina-core[ocr]) — defaults on for product UX
OCR_ENABLED = _env_bool("LUMINA_OCR_ENABLED", "1")
OCR_TIER = (os.getenv("LUMINA_OCR_TIER", "medium") or "medium").strip().lower()
OCR_LANG = (os.getenv("LUMINA_OCR_LANG", "ch") or "ch").strip()
OCR_PDF_DPI = _env_int("LUMINA_OCR_PDF_DPI", "150")
OCR_MIN_CONF = _env_float("LUMINA_OCR_MIN_CONF", "0.5")
OCR_PDF_TEXT_RATIO = _env_float("LUMINA_OCR_PDF_TEXT_RATIO", "0.15")


@dataclass(frozen=True)
class ChunkBudget:
    target_chars: int
    max_chars: int
    min_chars: int


def default_chunk_target_for_provider(provider: str) -> int:
    normalized = provider.strip().lower()
    if normalized == "ollama":
        return OLLAMA_CHUNK_TARGET
    if normalized == "openrouter":
        return OPENROUTER_CHUNK_TARGET
    return CLOUD_CHUNK_TARGET


def _chunk_budget_from_target(target: int) -> ChunkBudget:
    max_chars = max(target, int(target * 1.2))
    min_chars = max(1, int(target * 0.6))
    return ChunkBudget(
        target_chars=target,
        max_chars=max_chars,
        min_chars=min_chars,
    )


def resolve_resource_chunk_budget(resource: ModelResource) -> ChunkBudget:
    """Resolve segment chunk sizes for one API resource."""
    target = (
        resource.chunk_target_chars
        if resource.chunk_target_chars > 0
        else default_chunk_target_for_provider(resource.provider)
    )
    return _chunk_budget_from_target(target)


def resolve_chunk_budget(models: ModelsConfig | None = None) -> ChunkBudget:
    """Resolve segment chunk sizes from summarize primary resource or env overrides."""
    env_target = os.getenv("LUMINA_CHUNK_TARGET_CHARS")
    env_max = os.getenv("LUMINA_CHUNK_MAX_CHARS")

    if env_target:
        target = int(env_target)
        max_chars = int(env_max) if env_max else max(target, int(target * 1.2))
        min_chars = max(1, int(target * 0.6))
        return ChunkBudget(
            target_chars=target,
            max_chars=max(max_chars, target),
            min_chars=min_chars,
        )

    if models is not None:
        resources = models.resources_for_profile("summarize")
        if resources:
            budget = resolve_resource_chunk_budget(resources[0])
            if env_max:
                max_chars = max(int(env_max), budget.target_chars)
                return ChunkBudget(
                    target_chars=budget.target_chars,
                    max_chars=max_chars,
                    min_chars=budget.min_chars,
                )
            return budget

    budget = _chunk_budget_from_target(CLOUD_CHUNK_TARGET)
    if env_max:
        max_chars = max(int(env_max), budget.target_chars)
        return ChunkBudget(
            target_chars=budget.target_chars,
            max_chars=max_chars,
            min_chars=budget.min_chars,
        )
    return budget


def default_concurrency_for_provider(provider: str) -> int:
    normalized = provider.strip().lower()
    if normalized == "ollama":
        return 1
    if normalized == "cursor":
        return 8
    return 4


def effective_concurrency(resource: ModelResource) -> int:
    if resource.concurrency > 0:
        return resource.concurrency
    return default_concurrency_for_provider(resource.provider)


class ModelResource(BaseModel):
    id: str
    provider: str
    base_url: str = ""
    model: str = ""
    api_key: str | None = None
    chat_timeout: float = 12.0
    concurrency: int = 0  # 0 = use provider default
    chunk_target_chars: int = 0  # 0 = use provider default

    @field_validator("id")
    @classmethod
    def _normalize_id(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("provider")
    @classmethod
    def _normalize_provider(cls, value: str) -> str:
        return value.strip().lower()


class ProfileRoute(BaseModel):
    priority: list[str] = Field(default_factory=list)


# Legacy single-profile shape (migration only).
class ProfileConfig(BaseModel):
    provider: str = "ollama"
    model: str = "qwen3.5:4b"
    base_url: str = "http://127.0.0.1:11434"
    api_key: str | None = None


def default_resources() -> list[ModelResource]:
    return [
        ModelResource(
            id="ollama",
            provider="ollama",
            base_url="http://127.0.0.1:11434",
            model="qwen3.5:4b",
            concurrency=1,
        ),
        ModelResource(
            id="openai",
            provider="openai",
            base_url="https://api.openai.com/v1",
            model="gpt-4o-mini",
            concurrency=4,
        ),
        ModelResource(
            id="openrouter",
            provider="openrouter",
            base_url="https://openrouter.ai/api/v1",
            model="anthropic/claude-sonnet-4",
            concurrency=4,
        ),
        ModelResource(id="cursor", provider="cursor", model="composer-2.5", concurrency=8),
        ModelResource(
            id="aiping",
            provider="aiping",
            base_url="https://aiping.cn/api/v1",
            model="GLM-5.2",
            concurrency=4,
        ),
    ]


def _default_chat_route() -> ProfileRoute:
    return ProfileRoute(priority=["openai", "ollama"])


def _default_summarize_route() -> ProfileRoute:
    return ProfileRoute(priority=["ollama", "openrouter"])


class ModelsConfig(BaseModel):
    resources: list[ModelResource] = Field(default_factory=default_resources)
    chat: ProfileRoute = Field(default_factory=_default_chat_route)
    summarize: ProfileRoute = Field(default_factory=_default_summarize_route)
    translate: ProfileRoute | None = None

    def resource_by_id(self, resource_id: str) -> ModelResource | None:
        rid = resource_id.strip().lower()
        for resource in self.resources:
            if resource.id == rid:
                return resource
        return None

    def resources_for_profile(self, profile: str) -> list[ModelResource]:
        route: ProfileRoute
        if profile == "translate":
            route = self.translate if self.translate is not None else self.summarize
        else:
            route = getattr(self, profile)
        resolved: list[ModelResource] = []
        for resource_id in route.priority:
            resource = self.resource_by_id(resource_id)
            if resource is not None:
                resolved.append(resource)
        return resolved

    def uses_ollama_in(self, profile: str) -> bool:
        return any(r.provider == "ollama" for r in self.resources_for_profile(profile))

    def primary_summarize_is_ollama(self) -> bool:
        resources = self.resources_for_profile("summarize")
        return bool(resources) and resources[0].provider == "ollama"

    def primary_summarize_is_cloud(self) -> bool:
        resources = self.resources_for_profile("summarize")
        if not resources:
            return False
        return resources[0].provider != "ollama"

    def max_concurrency_for_profile(self, profile: str) -> int:
        resources = self.resources_for_profile(profile)
        if not resources:
            return 1
        return max(1, max(effective_concurrency(r) for r in resources))


def _resource_id_for_legacy(profile: ProfileConfig) -> str:
    provider = profile.provider.strip().lower()
    if provider in _BUILTIN_RESOURCE_IDS:
        return provider
    slug = re.sub(r"[^a-z0-9]+", "-", provider).strip("-") or "custom"
    if profile.base_url:
        host = profile.base_url.rstrip("/").split("//")[-1][:24]
        host_slug = re.sub(r"[^a-z0-9]+", "-", host.lower()).strip("-")
        if host_slug:
            return f"{slug}-{host_slug}"
    return slug


def is_legacy_models_format(raw: dict[str, Any]) -> bool:
    chat = raw.get("chat")
    return isinstance(chat, dict) and "provider" in chat and "priority" not in chat


def migrate_legacy_models(raw: dict[str, Any], *, base: dict[str, Any] | None = None) -> dict[str, Any]:
    """Convert pre-resource-pool models.json to resources + priority chains."""
    merged = dict(base or {})
    resources: dict[str, dict[str, Any]] = {
        r["id"]: dict(r) for r in merged.get("resources", [])
    }
    for preset in default_resources():
        resources.setdefault(preset.id, preset.model_dump())

    routes: dict[str, list[str]] = {"chat": [], "summarize": [], "translate": []}
    for profile in ("chat", "summarize", "translate"):
        block = raw.get(profile)
        if not isinstance(block, dict) or "provider" not in block:
            continue
        legacy = ProfileConfig.model_validate(block)
        resource_id = _resource_id_for_legacy(legacy)
        entry = resources.setdefault(
            resource_id,
            {
                "id": resource_id,
                "provider": legacy.provider,
                "base_url": legacy.base_url,
                "model": legacy.model,
            },
        )
        entry["provider"] = legacy.provider
        if legacy.base_url:
            entry["base_url"] = legacy.base_url
        if legacy.model:
            entry["model"] = legacy.model
        routes[profile] = [resource_id]

    out = dict(merged)
    out["resources"] = list(resources.values())
    if routes["chat"]:
        out["chat"] = {"priority": routes["chat"]}
    if routes["summarize"]:
        out["summarize"] = {"priority": routes["summarize"]}
    if routes["translate"]:
        out["translate"] = {"priority": routes["translate"]}
    elif routes["summarize"]:
        out["translate"] = None
    return migrate_job_concurrency_to_resources(out, raw.get("job_concurrency"))


def _legacy_concurrency_for_provider(provider: str, job_concurrency: dict[str, Any]) -> int:
    normalized = provider.strip().lower()
    if normalized == "ollama":
        return max(1, int(job_concurrency.get("ollama", 1)))
    if normalized == "cursor":
        return max(1, int(job_concurrency.get("cursor", 8)))
    return max(1, int(job_concurrency.get("cloud", 4)))


def migrate_job_concurrency_to_resources(
    raw: dict[str, Any],
    job_concurrency: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Move legacy top-level job_concurrency into per-resource concurrency fields."""
    out = dict(raw)
    jc = job_concurrency if job_concurrency is not None else out.pop("job_concurrency", None)
    if not isinstance(jc, dict):
        out.pop("job_concurrency", None)
        return out

    resources = out.get("resources") or []
    updated: list[dict[str, Any]] = []
    for item in resources:
        if not isinstance(item, dict):
            updated.append(item)
            continue
        entry = dict(item)
        if not entry.get("concurrency"):
            provider = str(entry.get("provider") or "")
            entry["concurrency"] = _legacy_concurrency_for_provider(provider, jc)
        updated.append(entry)
    out["resources"] = updated
    out.pop("job_concurrency", None)
    return out


def normalize_models_raw(raw: dict[str, Any]) -> dict[str, Any]:
    if is_legacy_models_format(raw):
        raw = migrate_legacy_models(raw)
    else:
        raw = migrate_job_concurrency_to_resources(raw)
    return raw


PROMPT_PLACEHOLDERS: dict[str, tuple[str, ...]] = {
    "segment": ("{text}", "{anchor}"),
    "segment_ollama": ("{text}",),
    "segment_cloud": ("{text}",),
    "document": ("{filename}", "{annotated}"),
    "translate": ("{target_language}", "{text}"),
    "classify": ("{categories}", "{title}", "{author}", "{text}"),
    "chat": (),
    "news_chat": (),
}


class PromptsConfig(BaseModel):
    segment: str
    segment_ollama: str | None = None
    segment_cloud: str | None = None
    document: str
    chat: str
    news_chat: str
    translate: str
    classify: str

    def validate_placeholders(self) -> None:
        errors: list[str] = []
        for field, required in PROMPT_PLACEHOLDERS.items():
            value = getattr(self, field)
            if value is None:
                if field in ("segment_ollama", "segment_cloud"):
                    continue
                errors.append(f"{field}: missing value")
                continue
            for placeholder in required:
                if placeholder not in value:
                    errors.append(f"{field}: missing placeholder {placeholder}")
        if errors:
            raise ValueError("; ".join(errors))


def load_prompts_config(path: Path | None = None) -> PromptsConfig:
    from lumina_core.prompts_defaults import (
        DEFAULT_CHAT,
        DEFAULT_CLASSIFY,
        DEFAULT_DOCUMENT,
        DEFAULT_NEWS_CHAT,
        DEFAULT_SEGMENT,
        DEFAULT_SEGMENT_CLOUD,
        DEFAULT_SEGMENT_OLLAMA,
        DEFAULT_TRANSLATE,
    )

    if path is None:
        root = bundle_root()
        if root is not None:
            path = root / "config" / "prompts.yaml"
        else:
            path = Path(__file__).resolve().parents[1] / "config" / "prompts.yaml"
    if not path.exists():
        return PromptsConfig(
            segment=DEFAULT_SEGMENT,
            segment_ollama=DEFAULT_SEGMENT_OLLAMA,
            segment_cloud=DEFAULT_SEGMENT_CLOUD,
            document=DEFAULT_DOCUMENT,
            chat=DEFAULT_CHAT,
            news_chat=DEFAULT_NEWS_CHAT,
            translate=DEFAULT_TRANSLATE,
            classify=DEFAULT_CLASSIFY,
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cfg = PromptsConfig.model_validate(raw)
    cfg.validate_placeholders()
    return cfg


def _platform_default_data_dir() -> Path:
    """OS-native application data directory for Lumina."""
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Lumina"
        return Path.home() / "AppData" / "Roaming" / "Lumina"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Lumina"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "Lumina"
    return Path.home() / ".local" / "share" / "Lumina"


class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 17432
    data_dir: Path = Field(default_factory=_platform_default_data_dir)
    target_language: str = "zh-CN"
    web_search_provider: str = "ddgs"  # ddgs | tavily
    tavily_api_key: str | None = None
    debug_mode: bool = False
    auto_start_summary: bool = False
    prompts: PromptsConfig | None = None

    class Config:
        env_prefix = "LUMINA_"


def default_data_dir() -> Path:
    override = os.getenv("LUMINA_DATA_DIR")
    if override:
        return Path(override)
    return _platform_default_data_dir()


def bundle_root() -> Path | None:
    """Directory next to frozen lumina-core executable (PyInstaller one-folder)."""
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
    return ModelsConfig.model_validate(normalize_models_raw(raw))


def apply_env_keys(cfg: ModelsConfig) -> ModelsConfig:
    data = cfg.model_dump()
    cursor_env = os.getenv("CURSOR_API_KEY")
    resources = data.get("resources") or []

    for resource in resources:
        rid = resource["id"]
        env_key = os.getenv(f"LUMINA_RESOURCE_{rid.upper().replace('-', '_')}_API_KEY")
        if env_key:
            resource["api_key"] = env_key
        elif resource.get("provider") == "cursor" and cursor_env:
            resource["api_key"] = cursor_env

    legacy_profile_keys = {
        "chat": os.getenv("LUMINA_CHAT_API_KEY"),
        "summarize": os.getenv("LUMINA_SUMMARIZE_API_KEY"),
        "translate": os.getenv("LUMINA_TRANSLATE_API_KEY"),
    }
    for profile, env_key in legacy_profile_keys.items():
        if not env_key:
            continue
        route = data.get(profile) or {}
        priority = route.get("priority") or []
        if not priority:
            continue
        target_id = priority[0]
        for resource in resources:
            if resource["id"] == target_id and not resource.get("api_key"):
                resource["api_key"] = env_key
                break

    return ModelsConfig.model_validate(data)
