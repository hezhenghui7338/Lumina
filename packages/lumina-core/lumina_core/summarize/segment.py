"""Segment summarization."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from lumina_core.config import (
    MAX_SUMMARY_RETRIES,
    OLLAMA_SUMMARY_MAX_RETRIES,
    OLLAMA_SUMMARY_MIN_BODY_CHARS,
    PromptsConfig,
    load_prompts_config,
    resolve_chunk_budget,
)
from lumina_core.models.router import ProfileModelRouter
from lumina_core.prompts_defaults import (
    DEFAULT_SEGMENT as SUMMARY_PROMPT,
    DEFAULT_SEGMENT_CLOUD as SUMMARY_PROMPT_CLOUD,
    DEFAULT_SEGMENT_OLLAMA as SUMMARY_PROMPT_OLLAMA,
)
from lumina_core.summarize.schema import (
    SegmentSummary,
    parse_segment_summary,
    parse_segment_summary_minimal,
    validate_summary_richness,
)

SummaryProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]

ProviderKind = Literal["ollama", "cloud", "full"]

_OLLAMA_RETRY_SUFFIX = (
    '\n\n上次输出不是合法 JSON。请只输出 '
    '{{"sentences":["…"],"bullets":[{{"label":"…","body":"…"}}],"follow_ups":["…"]}}，不要其他文字。'
)

_CLOUD_RETRY_SUFFIX = (
    '\n\n上次输出不是合法 JSON。请只输出 '
    '{{"sentences":["…"],"bullets":[{{"label":"…","body":"…"}}],"follow_ups":["…"]}}，不要其他文字。'
)


@dataclass
class SummarizeResult:
    summary: SegmentSummary
    llm_attempts: int
    llm_duration_s: float


def _segment_prompt_settings(
    router: ProfileModelRouter,
    prompts: PromptsConfig,
) -> tuple[str, int, int, int, bool, bool, ProviderKind]:
    """Return prompt template, text limit, retries, min body chars, text-only, minimal parse, provider kind."""
    models = getattr(router, "models", None)
    text_limit = resolve_chunk_budget(models).max_chars
    if models is not None and models.primary_summarize_is_ollama():
        template = prompts.segment_ollama or prompts.segment
        return (
            template,
            text_limit,
            OLLAMA_SUMMARY_MAX_RETRIES,
            OLLAMA_SUMMARY_MIN_BODY_CHARS,
            "{anchor}" not in template,
            True,
            "ollama",
        )
    if models is not None and models.primary_summarize_is_cloud():
        template = prompts.segment_cloud or prompts.segment
        return (
            template,
            text_limit,
            MAX_SUMMARY_RETRIES,
            OLLAMA_SUMMARY_MIN_BODY_CHARS,
            "{anchor}" not in template,
            True,
            "cloud",
        )
    return (
        prompts.segment,
        text_limit,
        MAX_SUMMARY_RETRIES,
        20,
        False,
        False,
        "full",
    )


def _format_base_prompt(
    template: str,
    *,
    anchor_label: str,
    text: str,
    text_only: bool,
) -> str:
    if text_only:
        return template.format(text=text)
    return template.format(anchor=anchor_label, text=text)


def summarize_job_timeout_seconds(
    router: ProfileModelRouter,
    prompts: PromptsConfig | None = None,
) -> int:
    """Wall-clock budget for one summarize job (each LLM attempt may use full segment timeout)."""
    from lumina_core import config

    resolved = prompts or load_prompts_config()
    _, _, llm_retries, _, _, _, _ = _segment_prompt_settings(router, resolved)
    return config.SUMMARY_SEGMENT_TIMEOUT_SECONDS * max(1, llm_retries)


async def summarize_segment(
    router: ProfileModelRouter,
    *,
    raw_text: str,
    anchor_label: str,
    max_retries: int | None = None,
    failure_dump_path: Path | None = None,
    on_progress: SummaryProgressCallback | None = None,
    prompts: PromptsConfig | None = None,
) -> SummarizeResult:
    resolved = prompts or load_prompts_config()
    prompt_template, text_limit, default_retries, min_body_chars, text_only, use_minimal_parse, provider_kind = (
        _segment_prompt_settings(router, resolved)
    )
    segment_text = raw_text[:text_limit]
    base_prompt = _format_base_prompt(
        prompt_template,
        anchor_label=anchor_label,
        text=segment_text,
        text_only=text_only,
    )
    prompt = base_prompt
    last_err: Exception | None = None
    last_raw: str | None = None
    retries = max_retries if max_retries is not None else default_retries
    total_llm_duration = 0.0

    async def _emit_progress(
        *,
        phase: str,
        llm_attempt: int,
        llm_duration_s: float | None = None,
    ) -> None:
        if on_progress is None:
            return
        payload: dict[str, Any] = {
            "type": "segment_summarize_progress",
            "phase": phase,
            "llm_attempt": llm_attempt,
            "max_llm_attempts": retries,
        }
        if llm_duration_s is not None:
            payload["llm_duration_s"] = llm_duration_s
        await on_progress(payload)

    for attempt in range(retries):
        import time

        from lumina_core.debug_agent_log import agent_log

        llm_attempt = attempt + 1
        await _emit_progress(phase="start", llm_attempt=llm_attempt)
        attempt_started = time.time()

        async def _on_slot_acquired() -> None:
            await _emit_progress(phase="llm_start", llm_attempt=llm_attempt)

        agent_log(
            hypothesis_id="B",
            location="segment.py:summarize_segment:attempt",
            message="LLM attempt start",
            data={
                "attempt": llm_attempt,
                "max_attempts": retries,
                "prompt_chars": len(prompt),
                "text_limit": text_limit,
            },
        )
        raw = await router.complete(
            prompt,
            profile="summarize",
            json_mode=True,
            on_slot_acquired=_on_slot_acquired,
        )
        llm_duration = round(time.time() - attempt_started, 2)
        total_llm_duration += llm_duration
        if isinstance(raw, str):
            last_raw = raw
        try:
            if use_minimal_parse:
                summary = parse_segment_summary_minimal(raw, fallback_anchor=anchor_label)
            else:
                summary = parse_segment_summary(raw)
                validate_summary_richness(summary, min_body_chars=min_body_chars)
            agent_log(
                hypothesis_id="B",
                location="segment.py:summarize_segment:success",
                message="LLM attempt succeeded",
                data={"attempt": llm_attempt, "llm_duration_s": llm_duration},
            )
            return SummarizeResult(
                summary=summary,
                llm_attempts=llm_attempt,
                llm_duration_s=round(total_llm_duration, 2),
            )
        except (ValidationError, json.JSONDecodeError, ValueError) as exc:
            last_err = exc
            agent_log(
                hypothesis_id="B",
                location="segment.py:summarize_segment:validation_fail",
                message="LLM output validation failed, will retry",
                data={
                    "attempt": llm_attempt,
                    "llm_duration_s": llm_duration,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:300],
                    "raw_len": len(last_raw or ""),
                },
            )
            await _emit_progress(
                phase="fail",
                llm_attempt=llm_attempt,
                llm_duration_s=llm_duration,
            )
        if attempt + 1 < retries and last_err is not None:
            if use_minimal_parse:
                suffix = _OLLAMA_RETRY_SUFFIX if provider_kind == "ollama" else _CLOUD_RETRY_SUFFIX
                prompt = base_prompt + suffix
            elif isinstance(last_err, json.JSONDecodeError):
                prompt = (
                    base_prompt
                    + "\n\n上次输出不是合法 JSON，请只输出一个完整 JSON 对象，不要任何解释文字；"
                    "bullets 须为 {{label, body}} 对象数组。"
                )
            elif isinstance(last_err, ValueError):
                prompt = (
                    base_prompt
                    + f"\n\n上次输出不符合要求：{last_err}。"
                    "bullets 每条 body 须充实说明，禁止只写标签；"
                    "follow_ups 须基于本段已覆盖内容。"
                )
            elif isinstance(last_err, ValidationError):
                prompt = (
                    base_prompt
                    + "\n\n上次输出字段不符合要求（如 label 须 ≤20 字、bullets 须 3～7 条），"
                    "请严格按规则重新输出单个 JSON 对象。"
                )
    assert last_err is not None
    if failure_dump_path is not None and last_raw is not None:
        failure_dump_path.parent.mkdir(parents=True, exist_ok=True)
        failure_dump_path.write_text(last_raw, encoding="utf-8")
    raise last_err


def summary_to_json(summary: SegmentSummary) -> str:
    return json.dumps(summary.model_dump(), ensure_ascii=False)


def segment_ready_event_payload(
    summary: SegmentSummary,
    *,
    idx: int,
    resource_id: str,
    model: str,
    summary_duration_s: float | None = None,
    summary_llm_attempts: int | None = None,
) -> dict[str, Any]:
    """SSE segment_ready payload with nested and flat summary fields for UI."""
    dumped = summary.model_dump()
    payload: dict[str, Any] = {
        "type": "segment_ready",
        "idx": idx,
        "label": summary.label,
        "summary_status": "ready",
        "summary_json": summary_to_json(summary),
        "anchor_label": summary.anchor,
        "summary_provider": resource_id,
        "summary_model": model,
        "sentences": dumped["sentences"],
        "bullets": dumped["bullets"],
        "notes": dumped["notes"],
        "follow_ups": dumped["follow_ups"],
        "anchor": dumped["anchor"],
    }
    if summary_duration_s is not None:
        payload["summary_duration_s"] = round(summary_duration_s, 2)
    if summary_llm_attempts is not None:
        payload["summary_llm_attempts"] = summary_llm_attempts
    return payload
