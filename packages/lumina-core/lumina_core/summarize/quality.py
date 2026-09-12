"""Hybrid, explainable quality checks for segment summaries."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Literal

from lumina_core.config import format_prompt
from lumina_core.models.router import ProfileModelRouter, parse_json_response
from lumina_core.summarize.schema import SegmentSummary
from lumina_core.translate.language import language_display_name, unexpected_language_span

logger = logging.getLogger(__name__)

IssueSeverity = Literal["hard", "soft", "model"]

_TEMPLATE_PATTERNS = (
    re.compile(r"```(?:json|markdown)?", re.IGNORECASE),
    re.compile(r'\{\s*"(?:sentences|bullets|label|body)"\s*:'),
    re.compile(r'"(?:sentences|bullets|label|body)"\s*:'),
    re.compile(r"(?m)^\s{0,3}#{1,6}\s+\S"),
)
_PLACEHOLDERS = frozenset({"…", "...", "待补充", "待完善", "tbd", "n/a", "（略）", "(略)"})
_TRAILING_CONNECTOR = re.compile(
    r"(?:因为|由于|以及|并且|但是|然而|却|从而|导致|例如|包括|即|也就是)[，,:：；;、]?$"
)
_REPEATED_PHRASE = re.compile(r"(.{4,12})\1{2,}")
_SYMBOL_RUN = re.compile(r"[{}\[\]<>|\\^~`*_#]{4,}")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ASSISTANT_IDENTITY = "阅读助手"
_NARRATOR_LABEL = "叙述者"
_FIRST_PERSON_WO = re.compile(r"我(?!国)")
_FIRST_PERSON_I = re.compile(r"\bI\b")
SENTENCES_TARGET_MIN = 50
SENTENCES_TARGET_MAX = 200
SENTENCES_REJECT_MIN = 40
SENTENCES_REJECT_MAX = 250
_ALWAYS_REJECT_CODES = frozenset(
    {
        "wrong_language",
        "first_person_as_narrator",
        "summary_too_short",
        "summary_too_long",
    }
)


def _source_uses_first_person(raw_text: str) -> bool:
    return (
        _FIRST_PERSON_WO.search(raw_text) is not None
        or _FIRST_PERSON_I.search(raw_text) is not None
    )


@dataclass(frozen=True)
class ClarityIssue:
    field: str
    code: str
    problem: str
    snippet: str
    severity: IssueSeverity
    start: int | None = None

    def prompt_line(self) -> str:
        snippet = self.snippet.replace("\n", " ").strip()[:60]
        return f"{self.field}：{self.problem}（“{snippet}”）"


@dataclass(frozen=True)
class QualityCheckResult:
    issues: tuple[ClarityIssue, ...]
    review_attempted: bool
    review_duration_s: float


class SummaryQualityError(ValueError):
    """Raised when a candidate summary has more than one clarity defect."""

    def __init__(self, issues: list[ClarityIssue] | tuple[ClarityIssue, ...]) -> None:
        self.issues = tuple(issues)
        details = "；".join(issue.prompt_line() for issue in self.issues[:4])
        super().__init__(f"摘要存在 {len(self.issues)} 处乱码、串语或表意不清：{details}")


def quality_should_reject(issues: tuple[ClarityIssue, ...] | list[ClarityIssue]) -> bool:
    """Always-reject codes fail alone; other defects still need more than one."""
    if any(issue.code in _ALWAYS_REJECT_CODES for issue in issues):
        return True
    return len(issues) > 1


def sentences_char_count(summary: SegmentSummary) -> int:
    """Unicode length of joined summary sentences (the on-screen 总结)."""
    return len("".join(summary.sentences))


def _summary_fields(summary: SegmentSummary) -> dict[str, str]:
    fields: dict[str, str] = {
        "label": summary.label,
    }
    fields.update({f"sentences[{i}]": text for i, text in enumerate(summary.sentences)})
    for i, bullet in enumerate(summary.bullets):
        fields[f"bullets[{i}].label"] = bullet.label
        fields[f"bullets[{i}].body"] = bullet.body
    fields.update({f"notes[{i}]": text for i, text in enumerate(summary.notes)})
    fields.update({f"follow_ups[{i}]": text for i, text in enumerate(summary.follow_ups)})
    return fields


def _snippet_at(text: str, start: int, length: int = 24) -> str:
    left = max(0, start - 8)
    return text[left : min(len(text), start + length)]


def scan_summary_clarity(
    summary: SegmentSummary,
    *,
    raw_text: str | None = None,
    target_language: str | None = "zh-CN",
) -> list[ClarityIssue]:
    """Return conservative local quality signals without calling a model."""
    issues: list[ClarityIssue] = []
    fields = _summary_fields(summary)
    check_identity_leak = raw_text is not None and _ASSISTANT_IDENTITY not in raw_text
    check_narrator_rewrite = (
        raw_text is not None
        and _NARRATOR_LABEL not in raw_text
        and _source_uses_first_person(raw_text)
    )

    for field, text in fields.items():
        stripped = text.strip()
        if check_identity_leak:
            start = text.find(_ASSISTANT_IDENTITY)
            if start >= 0:
                issues.append(
                    ClarityIssue(
                        field,
                        "assistant_identity_leak",
                        "把原文第一人称「我」写成阅读助手",
                        _snippet_at(text, start),
                        "hard",
                        start,
                    )
                )
        if check_narrator_rewrite:
            start = text.find(_NARRATOR_LABEL)
            if start >= 0:
                issues.append(
                    ClarityIssue(
                        field,
                        "first_person_as_narrator",
                        "把原文第一人称「我」改写成叙述者",
                        _snippet_at(text, start),
                        "hard",
                        start,
                    )
                )
        leak = unexpected_language_span(
            text, target_language=target_language, source_text=raw_text
        )
        if leak is not None:
            start, snippet, problem = leak
            issues.append(
                ClarityIssue(field, "wrong_language", problem, snippet, "hard", start)
            )
        for match in re.finditer("\ufffd", text):
            issues.append(
                ClarityIssue(
                    field, "replacement_char", "包含 Unicode 乱码替换字符", "�", "hard", match.start()
                )
            )
        for match in _CONTROL_CHARS.finditer(text):
            issues.append(
                ClarityIssue(
                    field,
                    "control_char",
                    "包含不可见控制字符",
                    repr(match.group()),
                    "hard",
                    match.start(),
                )
            )
        for pattern in _TEMPLATE_PATTERNS:
            for match in pattern.finditer(text):
                issues.append(
                    ClarityIssue(
                        field,
                        "template_leak",
                        "包含 JSON 或 Markdown 模板残留",
                        _snippet_at(text, match.start()),
                        "hard",
                        match.start(),
                    )
                )
        if stripped.casefold() in _PLACEHOLDERS:
            issues.append(
                ClarityIssue(field, "placeholder", "仍是占位文本", stripped, "hard", 0)
            )
        for match in _SYMBOL_RUN.finditer(text):
            issues.append(
                ClarityIssue(
                    field,
                    "symbol_noise",
                    "包含连续异常符号",
                    match.group(),
                    "hard",
                    match.start(),
                )
            )
        repeated = _REPEATED_PHRASE.search(text)
        if repeated:
            issues.append(
                ClarityIssue(
                    field,
                    "mechanical_repeat",
                    "同一短语机械重复",
                    repeated.group()[:60],
                    "hard",
                    repeated.start(),
                )
            )
        if len(stripped) >= 8 and _TRAILING_CONNECTOR.search(stripped):
            issues.append(
                ClarityIssue(
                    field,
                    "possible_truncation",
                    "句子疑似在连接词处截断",
                    stripped[-40:],
                    "soft",
                    max(0, len(text) - 40),
                )
            )

    for i, bullet in enumerate(summary.bullets):
        if bullet.body.strip() == bullet.label.strip():
            issues.append(
                ClarityIssue(
                    f"bullets[{i}].body",
                    "label_as_body",
                    "要点正文与标签相同，表意不足",
                    bullet.body,
                    "hard",
                    0,
                )
            )

    total = sentences_char_count(summary)
    joined = "".join(summary.sentences)
    source_len = len(raw_text.strip()) if raw_text is not None else None
    if total > SENTENCES_REJECT_MAX:
        issues.append(
            ClarityIssue(
                "sentences",
                "summary_too_long",
                f"总结合计约 {total} 字，明显超过目标上限 {SENTENCES_TARGET_MAX} 字",
                joined[:60],
                "hard",
                0,
            )
        )
    elif total < SENTENCES_REJECT_MIN and (
        source_len is None or source_len >= SENTENCES_TARGET_MIN
    ):
        issues.append(
            ClarityIssue(
                "sentences",
                "summary_too_short",
                f"总结合计约 {total} 字，明显短于目标下限 {SENTENCES_TARGET_MIN} 字",
                joined[:60] if joined else "（空）",
                "hard",
                0,
            )
        )
    return _dedupe_exact(issues)


def _dedupe_exact(issues: list[ClarityIssue]) -> list[ClarityIssue]:
    seen: set[tuple[str, str, int | None, str]] = set()
    out: list[ClarityIssue] = []
    for issue in issues:
        key = (issue.field, issue.code, issue.start, issue.snippet.strip().casefold())
        if key in seen:
            continue
        if issue.code == "template_leak" and any(
            existing.field == issue.field
            and existing.code == issue.code
            and existing.start is not None
            and issue.start is not None
            and abs(existing.start - issue.start) <= 3
            for existing in out
        ):
            continue
        seen.add(key)
        out.append(issue)
    return out


def _parse_model_issues(raw: str | dict, summary: SegmentSummary) -> list[ClarityIssue]:
    data = parse_json_response(raw) if isinstance(raw, str) else raw
    raw_issues = data.get("issues", [])
    if not isinstance(raw_issues, list):
        raise TypeError("quality review issues must be a list")

    fields = _summary_fields(summary)
    issues: list[ClarityIssue] = []
    for item in raw_issues[:8]:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "").strip()
        problem = str(item.get("problem") or "").strip()
        snippet = str(item.get("snippet") or "").strip()
        field_text = fields.get(field)
        if not field_text or not problem or not snippet or snippet not in field_text:
            continue
        issues.append(
            ClarityIssue(
                field=field,
                code="model_clarity",
                problem=problem[:100],
                snippet=snippet[:60],
                severity="model",
                start=field_text.find(snippet),
            )
        )
    return _dedupe_exact(issues)


def merge_clarity_issues(
    local_issues: list[ClarityIssue],
    model_issues: list[ClarityIssue],
) -> list[ClarityIssue]:
    """Merge issues while avoiding double-counting the same field location."""
    merged = [issue for issue in local_issues if issue.severity == "hard"]
    for candidate in model_issues:
        duplicate = any(
            existing.field == candidate.field
            and (
                existing.snippet in candidate.snippet
                or candidate.snippet in existing.snippet
                or (
                    existing.start is not None
                    and candidate.start is not None
                    and abs(existing.start - candidate.start) <= 3
                )
            )
            for existing in merged
        )
        if not duplicate:
            merged.append(candidate)
    return merged


async def inspect_summary_quality(
    router: ProfileModelRouter,
    *,
    raw_text: str,
    summary: SegmentSummary,
    review_prompt: str,
    summary_tier: Literal["normal", "advanced"] = "normal",
    target_language: str = "zh-CN",
) -> QualityCheckResult:
    """Apply local gates, then use a separate model call only for suspicious output."""
    local_issues = scan_summary_clarity(
        summary, raw_text=raw_text, target_language=target_language
    )
    hard_issues = [issue for issue in local_issues if issue.severity == "hard"]
    always_reject = [issue for issue in local_issues if issue.code in _ALWAYS_REJECT_CODES]
    if always_reject:
        rest = [issue for issue in hard_issues if issue.code not in _ALWAYS_REJECT_CODES]
        return QualityCheckResult(tuple(always_reject + rest), False, 0.0)
    if len(hard_issues) > 1:
        return QualityCheckResult(tuple(hard_issues), False, 0.0)
    if not local_issues:
        return QualityCheckResult((), False, 0.0)

    prompt = format_prompt(
        review_prompt,
        original_text=raw_text,
        summary_json=json.dumps(summary.model_dump(), ensure_ascii=False),
        target_language=language_display_name(target_language),
    )
    started = time.monotonic()
    try:
        raw_review = await router.complete(
            prompt,
            profile="summarize",
            summary_tier=summary_tier,
            json_mode=True,
        )
        model_issues = _parse_model_issues(raw_review, summary)
    except Exception as exc:  # noqa: BLE001 - optional supervision must fail open
        logger.warning("summary quality review failed; using local hard issues: %s", exc)
        model_issues = []
    duration = round(time.monotonic() - started, 2)
    issues = merge_clarity_issues(local_issues, model_issues)
    return QualityCheckResult(tuple(issues), True, duration)
