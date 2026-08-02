"""LLM translation."""

from __future__ import annotations

from lumina_core.config import PromptsConfig, load_prompts_config
from lumina_core.models.router import ProfileModelRouter
from lumina_core.prompts_defaults import DEFAULT_TRANSLATE as TRANSLATE_PROMPT


async def translate_segment(
    router: ProfileModelRouter,
    *,
    raw_text: str,
    target_language: str,
    prompts: PromptsConfig | None = None,
) -> str:
    template = (prompts or load_prompts_config()).translate
    prompt = template.format(
        target_language=target_language,
        text=raw_text[:8000],
    )
    return await router.complete(prompt, profile="translate", json_mode=False)
