"""Optional LLM cut offsets for advanced segmentation of unpunctuated spans."""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Protocol

from pydantic import BaseModel, Field

from lumina_core.chunker.semantic import (
    _SENTENCE_END,
    _paragraph_cut_offsets,
    _sentence_cut_offsets,
)
from lumina_core.config import DOCUMENT_MAP_TIMEOUT_SECONDS, PromptsConfig, load_prompts_config
from lumina_core.models.router import parse_json_response
from lumina_core.prompts_defaults import DEFAULT_BOUNDARY_CUTS

logger = logging.getLogger(__name__)


class Completer(Protocol):
    async def complete(
        self,
        prompt: str,
        *,
        profile: str = "summarize",
        json_mode: bool = False,
        **kwargs: Any,
    ) -> str: ...


class LlmCuts(BaseModel):
    offsets: list[int] = Field(default_factory=list)


def needs_llm_cut(chunk: str, *, max_chars: int) -> bool:
    """True for hard-capped or unpunctuated blocks that rules cannot split well."""
    if len(chunk) < max_chars * 0.8:
        return False
    if _SENTENCE_END.search(chunk) and "\n\n" in chunk:
        return False
    if not _SENTENCE_END.search(chunk):
        return True
    return len(chunk) >= max_chars


async def refine_spans_with_llm(
    text: str,
    spans: list[tuple[int, int]],
    *,
    max_chars: int,
    min_chars: int,
    router: Completer | None,
    prompts: PromptsConfig | None = None,
    cancel_event: threading.Event | None = None,
    timeout: float = DOCUMENT_MAP_TIMEOUT_SECONDS,
) -> list[tuple[int, int]]:
    """Split remaining oversized/unpunctuated spans via LLM offsets, then snap."""
    if router is None or not spans:
        return spans
    out: list[tuple[int, int]] = []
    cfg = prompts or load_prompts_config()
    template = getattr(cfg, "boundary_cuts", None) or DEFAULT_BOUNDARY_CUTS
    for start, end in spans:
        chunk = text[start:end]
        if cancel_event is not None and cancel_event.is_set():
            out.append((start, end))
            continue
        if not needs_llm_cut(chunk, max_chars=max_chars):
            out.append((start, end))
            continue
        cuts = await _llm_offsets(
            chunk,
            router=router,
            template=template,
            cancel_event=cancel_event,
            timeout=timeout,
        )
        split = _apply_relative_cuts(
            text,
            start,
            end,
            cuts,
            max_chars=max_chars,
            min_chars=min_chars,
        )
        out.extend(split)
    return out


async def _llm_offsets(
    chunk: str,
    *,
    router: Completer,
    template: str,
    cancel_event: threading.Event | None,
    timeout: float,
) -> list[int]:
    prompt = template.format(length=len(chunk), text=chunk[:8000])

    async def _call() -> str:
        return await router.complete(prompt, profile="summarize", json_mode=True)

    try:
        raw = await asyncio.wait_for(_call(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.info("boundary-cut LLM timed out; keeping rule spans")
        return []
    except Exception:
        logger.warning("boundary-cut LLM failed; keeping rule spans", exc_info=True)
        return []
    if cancel_event is not None and cancel_event.is_set():
        return []
    try:
        data = parse_json_response(raw) if isinstance(raw, str) else raw
        parsed = LlmCuts.model_validate(data)
    except Exception:
        logger.warning("boundary-cut response invalid; keeping rule spans", exc_info=True)
        return []
    return [int(value) for value in parsed.offsets if isinstance(value, (int, float))]


def _apply_relative_cuts(
    text: str,
    start: int,
    end: int,
    relative: list[int],
    *,
    max_chars: int,
    min_chars: int,
) -> list[tuple[int, int]]:
    points = [start]
    for rel in sorted(set(relative)):
        raw = start + int(rel)
        if raw <= start or raw >= end:
            continue
        cut = _snap_offset(text, start, end, raw, min_chars=min_chars, max_chars=max_chars)
        if cut is not None and points[-1] < cut < end:
            points.append(cut)
    points.append(end)
    spans = [(left, right) for left, right in zip(points, points[1:]) if right > left]
    return spans or [(start, end)]


def _snap_offset(
    text: str,
    start: int,
    end: int,
    target: int,
    *,
    min_chars: int,
    max_chars: int,
) -> int | None:
    paragraphs = _paragraph_cut_offsets(text, start, end)
    sentences = _sentence_cut_offsets(text, start, end)
    lo = start + max(1, min(min_chars, (end - start) // 4))
    hi = end - max(1, min(min_chars, (end - start) // 4))
    for group in (paragraphs, sentences):
        window = [point for point in group if lo <= point <= hi]
        if window:
            return min(window, key=lambda point: (abs(point - target), point))
    for group in (paragraphs, sentences):
        window = [point for point in group if start < point < end]
        if window:
            return min(window, key=lambda point: (abs(point - target), point))
    if start < target < end and target - start <= max_chars:
        return target
    return None
