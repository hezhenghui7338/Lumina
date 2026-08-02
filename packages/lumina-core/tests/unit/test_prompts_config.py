"""Prompts configuration load/merge/validation tests."""

from __future__ import annotations

import json

import pytest

from lumina_core.config import PromptsConfig, load_prompts_config
from lumina_core.prompts_store import default_prompts, load_prompts, merge_prompts


def test_load_prompts_config_has_required_placeholders():
    cfg = load_prompts_config()
    cfg.validate_placeholders()


def test_load_prompts_config_matches_defaults_module():
    cfg = load_prompts_config()
    defaults = default_prompts()
    assert cfg.segment == defaults.segment
    assert cfg.document == defaults.document


def test_validate_placeholders_rejects_missing_segment_anchor():
    cfg = load_prompts_config()
    cfg.segment = "only {text}"
    with pytest.raises(ValueError, match="segment: missing placeholder"):
        cfg.validate_placeholders()


def test_merge_prompts_clears_optional_overrides():
    base = load_prompts_config()
    existing = base.model_copy(update={"segment_ollama": "custom {text}"})
    incoming = PromptsConfig(
        segment=existing.segment,
        segment_ollama=None,
        segment_cloud=None,
        document=existing.document,
        chat=existing.chat,
        news_chat=existing.news_chat,
        translate=existing.translate,
        classify=existing.classify,
    )
    merged = merge_prompts(incoming, existing)
    assert merged.segment_ollama is None


def test_load_prompts_overlays_config_json(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    defaults = default_prompts()
    custom_segment = defaults.segment.replace("阅读助手", "自定义助手")
    (data_dir / "config.json").write_text(
        json.dumps({"prompts": {"segment": custom_segment}}, ensure_ascii=False),
        encoding="utf-8",
    )
    loaded = load_prompts(data_dir)
    assert "自定义助手" in loaded.segment
    assert loaded.document == defaults.document
