"""Config path resolution."""

from lumina_core.config import (
    CLOUD_CHUNK_MAX,
    CLOUD_CHUNK_TARGET,
    OLLAMA_CHUNK_MAX,
    OLLAMA_CHUNK_TARGET,
    OPENROUTER_CHUNK_MAX,
    OPENROUTER_CHUNK_TARGET,
    ModelsConfig,
    ProfileRoute,
    ModelResource,
    bundle_root,
    default_chunk_target_for_provider,
    effective_concurrency,
    load_models_config,
    normalize_models_raw,
    resolve_chunk_budget,
    resolve_resource_chunk_budget,
)


def test_load_models_config_from_dev_tree():
    cfg = load_models_config()
    ollama = cfg.resource_by_id("ollama")
    openai = cfg.resource_by_id("openai")
    assert ollama is not None
    assert ollama.model == "qwen3.5:4b"
    assert openai is not None
    assert openai.provider == "openai"
    assert cfg.summarize.priority == ["ollama", "openrouter"]
    assert cfg.chat.priority == ["openai", "ollama"]
    assert effective_concurrency(cfg.resource_by_id("ollama")) == 1
    assert effective_concurrency(cfg.resource_by_id("cursor")) == 8


def test_bundle_root_none_in_dev():
    assert bundle_root() is None


def test_resolve_chunk_budget_ollama_default():
    cfg = load_models_config()
    budget = resolve_chunk_budget(cfg)
    assert budget.target_chars == OLLAMA_CHUNK_TARGET
    assert budget.max_chars == OLLAMA_CHUNK_MAX


def test_resolve_chunk_budget_cloud_when_summarize_not_ollama():
    cfg = ModelsConfig(
        resources=[
            ModelResource(id="openai", provider="openai", model="gpt-4o-mini"),
        ],
        chat=ProfileRoute(priority=["openai"]),
        summarize=ProfileRoute(priority=["openai"]),
    )
    budget = resolve_chunk_budget(cfg)
    assert budget.target_chars == CLOUD_CHUNK_TARGET
    assert budget.max_chars == CLOUD_CHUNK_MAX


def test_resolve_chunk_budget_env_override(monkeypatch):
    monkeypatch.setenv("LUMINA_CHUNK_TARGET_CHARS", "800")
    monkeypatch.setenv("LUMINA_CHUNK_MAX_CHARS", "960")
    budget = resolve_chunk_budget()
    assert budget.target_chars == 800
    assert budget.max_chars == 960
    assert budget.min_chars == 480


def test_default_chunk_target_for_provider():
    assert default_chunk_target_for_provider("ollama") == OLLAMA_CHUNK_TARGET
    assert default_chunk_target_for_provider("openrouter") == OPENROUTER_CHUNK_TARGET
    assert default_chunk_target_for_provider("openai") == CLOUD_CHUNK_TARGET


def test_resolve_resource_chunk_budget_provider_defaults():
    ollama = ModelResource(id="ollama", provider="ollama", model="m")
    openrouter = ModelResource(id="openrouter", provider="openrouter", model="m")
    openai = ModelResource(id="openai", provider="openai", model="m")

    ollama_budget = resolve_resource_chunk_budget(ollama)
    assert ollama_budget.target_chars == OLLAMA_CHUNK_TARGET
    assert ollama_budget.max_chars == OLLAMA_CHUNK_MAX

    openrouter_budget = resolve_resource_chunk_budget(openrouter)
    assert openrouter_budget.target_chars == OPENROUTER_CHUNK_TARGET
    assert openrouter_budget.max_chars == OPENROUTER_CHUNK_MAX

    openai_budget = resolve_resource_chunk_budget(openai)
    assert openai_budget.target_chars == CLOUD_CHUNK_TARGET
    assert openai_budget.max_chars == CLOUD_CHUNK_MAX


def test_resolve_resource_chunk_budget_override():
    resource = ModelResource(
        id="openrouter",
        provider="openrouter",
        model="m",
        chunk_target_chars=5000,
    )
    budget = resolve_resource_chunk_budget(resource)
    assert budget.target_chars == 5000
    assert budget.max_chars == 6000
    assert budget.min_chars == 3000


def test_resolve_chunk_budget_openrouter_primary():
    cfg = ModelsConfig(
        resources=[
            ModelResource(id="openrouter", provider="openrouter", model="m"),
        ],
        chat=ProfileRoute(priority=["openrouter"]),
        summarize=ProfileRoute(priority=["openrouter"]),
    )
    budget = resolve_chunk_budget(cfg)
    assert budget.target_chars == OPENROUTER_CHUNK_TARGET
    assert budget.max_chars == OPENROUTER_CHUNK_MAX


def test_normalize_models_raw_migrates_job_concurrency():
    raw = normalize_models_raw(
        {
            "resources": [{"id": "ollama", "provider": "ollama", "model": "m"}],
            "job_concurrency": {"ollama": 3, "cloud": 5},
        }
    )
    assert "job_concurrency" not in raw
    assert raw["resources"][0]["concurrency"] == 3
