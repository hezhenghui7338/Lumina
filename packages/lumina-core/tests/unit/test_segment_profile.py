"""Type-based chunk targets and classical / English profile rules."""

from lumina_core.chunker.semantic import detect_classical_sample
from lumina_core.classify.segment_profile import (
    apply_english_chunk_factor,
    build_segment_profile_local,
    suggested_chunk_target,
)
from lumina_core.config import (
    CLASSICAL_CHUNK_TARGET,
    ModelsConfig,
    ModelResource,
    ProfileRoute,
    RESEGMENT_MIN_TARGET_CHARS,
    clamp_english_chunk_factor,
    resolve_chunk_budget,
    type_chunk_target,
)


_CLASSICAL_SAMPLE = (
    "子曰：学而时习之，不亦说乎？有朋自远方来，不亦乐乎？"
    "人不知而不愠，不亦君子乎？曾子曰：吾日三省吾身。"
    "为人谋而不忠乎？与朋友交而不信乎？传不习乎？"
    "子曰：道千乘之国，敬事而信，节用而爱人，使民以时。"
)


def test_type_chunk_target_table():
    assert type_chunk_target(category="文学") == 2000
    assert type_chunk_target(category="科技") == 500
    assert type_chunk_target(category="历史") == 1500
    assert type_chunk_target(category="哲学") == 800
    assert type_chunk_target(classical=True) == CLASSICAL_CHUNK_TARGET
    assert type_chunk_target(category="其他") is None


def test_suggested_classical_overrides_literature():
    assert (
        suggested_chunk_target(
            category="文学",
            classical=True,
            language="zh",
            english_chunk_factor=0.55,
            provider_default=2000,
        )
        == CLASSICAL_CHUNK_TARGET
    )


def test_suggested_english_scales_and_clamps():
    scaled = suggested_chunk_target(
        category="文学",
        classical=False,
        language="en",
        english_chunk_factor=0.55,
        provider_default=2000,
    )
    assert scaled == 1100
    assert (
        apply_english_chunk_factor(
            200,
            language="en",
            english_chunk_factor=0.30,
        )
        == RESEGMENT_MIN_TARGET_CHARS
    )


def test_english_factor_clamp():
    assert clamp_english_chunk_factor(0.1) == 0.30
    assert clamp_english_chunk_factor(2.0) == 1.00
    assert clamp_english_chunk_factor(None) == 0.55


def test_detect_classical_sample_positive():
    assert detect_classical_sample(_CLASSICAL_SAMPLE) is True
    assert detect_classical_sample("我们今天讨论这个问题，已经可以得出结论。") is False


def test_build_local_profile_classical():
    profile = build_segment_profile_local(
        _CLASSICAL_SAMPLE,
        models=None,
        english_chunk_factor=0.55,
        category="文学",
    )
    assert profile.classical is True
    assert profile.text_style == "classical"
    assert profile.chunk_target_chars == CLASSICAL_CHUNK_TARGET


def test_resolve_chunk_budget_explicit_wins_over_type():
    cfg = ModelsConfig(
        resources=[
            ModelResource(id="ollama", provider="ollama", model="qwen3.5:4b"),
        ],
        summarize=ProfileRoute(priority=["ollama"]),
    )
    budget = resolve_chunk_budget(
        cfg,
        target_chars=1500,
        category="科技",
        classical=True,
        language="en",
        english_chunk_factor=0.55,
    )
    assert budget.target_chars == 1500


def test_resolve_chunk_budget_type_table_when_resource_default():
    cfg = ModelsConfig(
        resources=[
            ModelResource(
                id="ollama",
                provider="ollama",
                model="qwen3.5:4b",
                chunk_target_chars=0,
            ),
        ],
        summarize=ProfileRoute(priority=["ollama"]),
    )
    budget = resolve_chunk_budget(
        cfg,
        category="科技",
        classical=False,
        language="zh",
        english_chunk_factor=0.55,
    )
    assert budget.target_chars == 500


def test_resolve_chunk_budget_resource_override_wins():
    cfg = ModelsConfig(
        resources=[
            ModelResource(
                id="ollama",
                provider="ollama",
                model="qwen3.5:4b",
                chunk_target_chars=2800,
            ),
        ],
        summarize=ProfileRoute(priority=["ollama"]),
    )
    budget = resolve_chunk_budget(
        cfg,
        category="科技",
        classical=False,
        language="zh",
        english_chunk_factor=0.55,
    )
    assert budget.target_chars == 2800
