"""Pre-chunk book profile: category, classical style, language → chunk target."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from lumina_core.chunker.semantic import detect_classical_sample
from lumina_core.classify.book import DEFAULT_CATEGORY, classify_book, normalize_category
from lumina_core.config import (
    RESEGMENT_MAX_TARGET_CHARS,
    RESEGMENT_MIN_TARGET_CHARS,
    ModelsConfig,
    PromptsConfig,
    clamp_english_chunk_factor,
    default_chunk_target_for_provider,
    type_chunk_target,
)
from lumina_core.models.router import ProfileModelRouter
from lumina_core.translate.language import infer_language, normalize_lang

logger = logging.getLogger(__name__)

TEXT_STYLE_CLASSICAL = "classical"
TEXT_STYLE_PROSE = "prose"
_PROFILE_SAMPLE_CHARS = 4000


@dataclass(frozen=True)
class SegmentProfile:
    category: str
    text_style: str
    language: str | None
    chunk_target_chars: int
    classical: bool

    def metadata_fields(self) -> dict[str, Any]:
        return {
            "text_style": self.text_style,
            "chunk_target_chars": self.chunk_target_chars,
            "segment_profile_category": self.category,
        }


def clamp_chunk_target(value: int) -> int:
    return max(
        RESEGMENT_MIN_TARGET_CHARS,
        min(RESEGMENT_MAX_TARGET_CHARS, int(value)),
    )


def apply_english_chunk_factor(
    target: int,
    *,
    language: str | None,
    english_chunk_factor: float,
) -> int:
    family = normalize_lang(language)
    if family != "en":
        return clamp_chunk_target(target)
    factor = clamp_english_chunk_factor(english_chunk_factor)
    return clamp_chunk_target(max(1, int(round(target * factor))))


def suggested_chunk_target(
    *,
    category: str | None,
    classical: bool,
    language: str | None,
    english_chunk_factor: float,
    provider_default: int,
) -> int:
    """Type table × English factor; classical forces 200 before English scale."""
    if classical:
        base = type_chunk_target(classical=True)
    else:
        mapped = type_chunk_target(category=category, classical=False)
        base = mapped if mapped is not None else provider_default
    return apply_english_chunk_factor(
        base,
        language=language,
        english_chunk_factor=english_chunk_factor,
    )


def provider_default_from_models(models: ModelsConfig | None) -> int:
    if models is None:
        return default_chunk_target_for_provider("openai")
    resources = models.resources_for_profile("summarize")
    if not resources:
        return default_chunk_target_for_provider("openai")
    resource = resources[0]
    if resource.chunk_target_chars > 0:
        return resource.chunk_target_chars
    return default_chunk_target_for_provider(resource.provider)


def build_segment_profile_local(
    text_sample: str,
    *,
    models: ModelsConfig | None,
    english_chunk_factor: float,
    category: str | None = None,
) -> SegmentProfile:
    """Classical + language heuristics; optional category (default 其他)."""
    sample = (text_sample or "")[:_PROFILE_SAMPLE_CHARS]
    classical = detect_classical_sample(sample)
    language = infer_language(sample)
    resolved_category = normalize_category(category) if category else DEFAULT_CATEGORY
    if classical and resolved_category == DEFAULT_CATEGORY:
        # Classical prose still shows as 文学 on the shelf when LLM did not run.
        resolved_category = "文学"
    provider_default = provider_default_from_models(models)
    target = suggested_chunk_target(
        category=resolved_category,
        classical=classical,
        language=language,
        english_chunk_factor=english_chunk_factor,
        provider_default=provider_default,
    )
    return SegmentProfile(
        category=resolved_category,
        text_style=TEXT_STYLE_CLASSICAL if classical else TEXT_STYLE_PROSE,
        language=language,
        chunk_target_chars=target,
        classical=classical,
    )


async def build_segment_profile(
    *,
    title: str,
    author: str | None,
    text_sample: str,
    models: ModelsConfig | None,
    english_chunk_factor: float,
    router: ProfileModelRouter | None = None,
    prompts: PromptsConfig | None = None,
) -> SegmentProfile:
    """Local heuristics + optional LLM category before chunking."""
    category: str | None = None
    if router is not None:
        try:
            category = await classify_book(
                router,
                title=title or "",
                author=author,
                text_sample=(text_sample or "")[:2000],
                prompts=prompts,
            )
        except Exception:
            logger.exception("pre-chunk classify failed; falling back to 其他")
            category = None
    return build_segment_profile_local(
        text_sample,
        models=models,
        english_chunk_factor=english_chunk_factor,
        category=category,
    )


def peek_txt_sample(path: Any, *, max_chars: int = _PROFILE_SAMPLE_CHARS) -> str:
    """Decode a short prefix of a TXT file for pre-chunk profiling."""
    from pathlib import Path

    from lumina_core.ingest.text import detect_encoding_plan

    file_path = Path(path)
    raw = file_path.read_bytes()[: max(8192, max_chars * 4)]
    if not raw:
        return ""
    plan = detect_encoding_plan(raw[:8192])
    try:
        return raw.decode(plan.encoding, errors="replace")[:max_chars]
    except LookupError:
        return raw.decode("utf-8", errors="replace")[:max_chars]
