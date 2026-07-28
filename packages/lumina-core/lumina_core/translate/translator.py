"""LLM translation."""

from __future__ import annotations

from lumina_core.models.router import ProfileModelRouter

TRANSLATE_PROMPT = """将以下文本翻译为{target_language}。保持术语一致，只输出译文。

---
{text}
"""


async def translate_segment(
    router: ProfileModelRouter,
    *,
    raw_text: str,
    target_language: str,
) -> str:
    prompt = TRANSLATE_PROMPT.format(
        target_language=target_language,
        text=raw_text[:8000],
    )
    return await router.complete(prompt, profile="translate", json_mode=False)
