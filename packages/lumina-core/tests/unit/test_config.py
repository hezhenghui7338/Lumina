"""Config path resolution."""

from lumina_core.config import (
    CLOUD_CHUNK_MAX,
    CLOUD_CHUNK_TARGET,
    OLLAMA_CHUNK_MAX,
    OLLAMA_CHUNK_TARGET,
    ModelsConfig,
    ProfileRoute,
    ModelResource,
    bundle_root,
    effective_concurrency,
    load_models_config,
    normalize_models_raw,
    resolve_chunk_budget,
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


def test_normalize_models_raw_migrates_job_concurrency():
    raw = normalize_models_raw(
        {
            "resources": [{"id": "ollama", "provider": "ollama", "model": "m"}],
            "job_concurrency": {"ollama": 3, "cloud": 5},
        }
    )
    assert "job_concurrency" not in raw
    assert raw["resources"][0]["concurrency"] == 3
