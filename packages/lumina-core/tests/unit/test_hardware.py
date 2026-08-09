"""Hardware helpers."""

from lumina_core.hardware import (
    DEFAULT_TIER_MODEL,
    format_ram_gb,
    recommend_ollama_model,
    total_ram_bytes,
)


def test_recommend_ollama_model_tiers(monkeypatch):
    # None means "probe machine"; stub probe so CI RAM does not change the default.
    monkeypatch.setattr("lumina_core.hardware.total_ram_bytes", lambda: None)
    assert recommend_ollama_model(None) == DEFAULT_TIER_MODEL
    assert recommend_ollama_model(2 * (1024**3)) == "qwen3.5:0.8b"
    assert recommend_ollama_model(8 * (1024**3)) == "qwen3.5:2b"
    assert recommend_ollama_model(12 * (1024**3)) == "qwen3.5:4b"
    assert recommend_ollama_model(20 * (1024**3)) == "qwen3.5:9b"


def test_format_ram_gb():
    assert format_ram_gb(None) == "unknown"
    assert format_ram_gb(16 * (1024**3)) == "16.0 GB"


def test_total_ram_bytes_returns_positive_or_none():
    ram = total_ram_bytes()
    assert ram is None or ram > 0
