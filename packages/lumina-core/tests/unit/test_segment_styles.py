"""Per-category segment summary style resolution and prompt injection."""

from __future__ import annotations

import json

from lumina_core.config import PromptsConfig, load_prompts_config, normalize_segment_styles
from lumina_core.prompts_defaults import DEFAULT_SEGMENT_STYLES
from lumina_core.prompts_store import default_prompts, load_prompts, merge_prompts
from lumina_core.summarize.segment import _format_base_prompt
from lumina_core.summarize.segment_styles import (
    resolve_segment_style_guidance,
    resolve_segment_style_key,
)


def test_resolve_style_key_classical_wins():
    assert resolve_segment_style_key(category="科技", text_style="classical") == "古文"
    assert resolve_segment_style_key(category="文学", text_style="prose") == "文学"
    assert resolve_segment_style_key(category=None, text_style=None) == "其他"
    assert resolve_segment_style_key(category="未知类", text_style=None) == "其他"


def test_resolve_guidance_uses_category_and_overlay():
    prompts = load_prompts_config()
    tech = resolve_segment_style_guidance(prompts, category="科技")
    assert "冷静" in tech or "术语" in tech
    literary = resolve_segment_style_guidance(prompts, category="文学")
    assert literary != tech
    classical = resolve_segment_style_guidance(
        prompts, category="科技", text_style="classical"
    )
    assert "白话" in classical or "文言" in classical

    custom = prompts.model_copy(
        update={
            "segment_styles": normalize_segment_styles(
                {**(prompts.segment_styles or {}), "科技": "自定义科技语气包"}
            )
        }
    )
    assert resolve_segment_style_guidance(custom, category="科技") == "自定义科技语气包"


def test_format_base_prompt_injects_style_guidance():
    prompts = load_prompts_config()
    guidance = resolve_segment_style_guidance(prompts, category="传记")
    prompt = _format_base_prompt(
        prompts.segment,
        anchor_label="§1 · 段 1",
        text="我回忆童年。",
        text_only=False,
        target_language="zh-CN",
        style_guidance=guidance,
    )
    assert "{style_guidance}" not in prompt
    assert guidance in prompt
    assert "我回忆童年。" in prompt


def test_format_base_prompt_appends_style_when_placeholder_missing():
    prompt = _format_base_prompt(
        "只总结 {text}",
        anchor_label="§1",
        text="hello",
        text_only=True,
        target_language="zh-CN",
        style_guidance="科技冷静语气",
    )
    assert "科技冷静语气" in prompt
    assert "只总结 hello" in prompt


def test_load_prompts_overlays_segment_styles(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "config.json").write_text(
        json.dumps(
            {"prompts": {"segment_styles": {"科技": "用户覆盖科技风格"}}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    loaded = load_prompts(data_dir)
    assert loaded.segment_styles is not None
    assert loaded.segment_styles["科技"] == "用户覆盖科技风格"
    assert loaded.segment_styles["文学"] == DEFAULT_SEGMENT_STYLES["文学"]


def test_merge_prompts_segment_styles():
    existing = default_prompts()
    incoming = PromptsConfig(
        segment=existing.segment,
        document=existing.document,
        chat=existing.chat,
        news_chat=existing.news_chat,
        translate=existing.translate,
        classify=existing.classify,
        segment_styles={"历史": "自定义历史风格"},
    )
    merged = merge_prompts(incoming, existing)
    assert merged.segment_styles is not None
    assert merged.segment_styles["历史"] == "自定义历史风格"
    assert merged.segment_styles["哲学"] == DEFAULT_SEGMENT_STYLES["哲学"]


def test_bundled_prompts_include_style_placeholder_and_keys():
    cfg = load_prompts_config()
    assert "{style_guidance}" in cfg.segment
    assert cfg.segment_ollama is not None and "{style_guidance}" in cfg.segment_ollama
    assert cfg.segment_cloud is not None and "{style_guidance}" in cfg.segment_cloud
    assert cfg.segment_styles is not None
    for key in ("文学", "历史", "科技", "哲学", "经济", "传记", "其他", "古文"):
        assert key in cfg.segment_styles
        assert cfg.segment_styles[key].strip()
