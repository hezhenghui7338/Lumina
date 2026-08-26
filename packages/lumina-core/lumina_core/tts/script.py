"""Shared listen-script contract (Python is the source of truth for clients)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from lumina_core.summarize.schema import parse_json_response

ListenMode = Literal["summary", "detailed", "original"]
LISTEN_MODES: tuple[str, ...] = ("summary", "detailed", "original")

SECTION_BULLETS = "结构化要点"
SECTION_NOTES = "需要注意"

# Keep utterances short enough for OpenAI TTS (4096) and natural pauses.
MAX_UTTERANCE_CHARS = 800

_SENTENCE_SPLIT = re.compile(
    r"(?<=[。！？；!?])\s*|(?<=\.(?!\d))\s+|(?<=[!?])\s+|\n+"
)
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


@dataclass(frozen=True)
class ListenUtterance:
    text: str


@dataclass(frozen=True)
class ListenScript:
    mode: ListenMode
    language: str
    utterances: list[ListenUtterance] = field(default_factory=list)
    ready: bool = True
    skip_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "language": self.language,
            "utterances": [{"text": u.text} for u in self.utterances],
            "ready": self.ready,
            "skip_reason": self.skip_reason,
        }


def detect_language(text: str) -> str:
    """Return `zh` or `en` from CJK vs Latin letter counts."""
    if not text or not text.strip():
        return "zh"
    cjk = len(_CJK_RE.findall(text))
    letters = sum(1 for ch in text if ("A" <= ch <= "Z") or ("a" <= ch <= "z"))
    if cjk >= max(1, letters):
        return "zh"
    return "en"


def _not_ready(mode: ListenMode, reason: str, language: str = "zh") -> ListenScript:
    return ListenScript(
        mode=mode,
        language=language,
        utterances=[],
        ready=False,
        skip_reason=reason,
    )


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _split_sentences(text: str) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(raw) if p and p.strip()]
    if not parts:
        parts = [raw]
    return parts


def _chunk_long(text: str, max_chars: int = MAX_UTTERANCE_CHARS) -> list[str]:
    cleaned = _clean(text)
    if not cleaned:
        return []
    if len(cleaned) <= max_chars:
        return [cleaned]
    chunks: list[str] = []
    remaining = cleaned
    while remaining:
        if len(remaining) <= max_chars:
            chunks.append(remaining)
            break
        window = remaining[:max_chars]
        cut = max(
            window.rfind("。"),
            window.rfind("！"),
            window.rfind("？"),
            window.rfind("；"),
            window.rfind("，"),
            window.rfind(". "),
            window.rfind(" "),
        )
        if cut < max_chars // 3:
            cut = max_chars
        else:
            cut = cut + 1
        piece = remaining[:cut].strip()
        if piece:
            chunks.append(piece)
        remaining = remaining[cut:].strip()
    return chunks


def _utterances_from_texts(texts: list[str]) -> list[ListenUtterance]:
    out: list[ListenUtterance] = []
    for text in texts:
        for chunk in _chunk_long(text):
            out.append(ListenUtterance(text=chunk))
    return out


def _parse_summary_payload(summary_json: str | dict[str, Any] | None) -> dict[str, Any] | None:
    if summary_json is None:
        return None
    if isinstance(summary_json, dict):
        data = summary_json
    else:
        raw = str(summary_json).strip()
        if not raw:
            return None
        try:
            parsed = parse_json_response(raw)
        except (ValueError, TypeError):
            return None
        if not isinstance(parsed, dict):
            return None
        data = parsed
    return data


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


def _bullets(value: object) -> list[tuple[str, str]]:
    if not isinstance(value, list):
        return []
    out: list[tuple[str, str]] = []
    for item in value:
        if isinstance(item, dict):
            label = str(item.get("label") or "").strip()
            body = str(item.get("body") or item.get("content") or item.get("text") or "").strip()
            if not body and label:
                body = label
                label = ""
            if body:
                out.append((label, body))
        elif isinstance(item, str) and item.strip():
            out.append(("", item.strip()))
    return out


def _format_bullet(index: int, label: str, body: str) -> str:
    if label:
        return f"{index}. {label}。{body}"
    return f"{index}. {body}"


def build_listen_script(
    *,
    mode: str,
    summary_json: str | dict[str, Any] | None = None,
    raw_text: str | None = None,
    language_hint: str | None = None,
) -> ListenScript:
    """Build speakable utterances. Never includes follow_ups or notes."""
    normalized = (mode or "").strip().lower()
    if normalized not in LISTEN_MODES:
        raise ValueError(f"unsupported listen mode: {mode}")
    typed_mode: ListenMode = normalized  # type: ignore[assignment]

    if typed_mode == "original":
        text = (raw_text or "").strip()
        if not text:
            return _not_ready(typed_mode, "empty_text", language_hint or "zh")
        sentences = _split_sentences(text)
        utterances = _utterances_from_texts(sentences)
        language = language_hint or detect_language(text)
        if not utterances:
            return _not_ready(typed_mode, "empty_text", language)
        return ListenScript(mode=typed_mode, language=language, utterances=utterances)

    payload = _parse_summary_payload(summary_json)
    if payload is None:
        return _not_ready(typed_mode, "summary_not_ready", language_hint or "zh")

    sentences = _string_list(payload.get("sentences"))
    bullets = _bullets(payload.get("bullets"))
    notes = _string_list(payload.get("notes"))
    sample = " ".join(sentences + [body for _, body in bullets] + notes)
    language = language_hint or detect_language(sample)

    lines: list[str] = []
    lines.extend(sentences)

    if typed_mode == "detailed":
        if bullets:
            lines.append(SECTION_BULLETS)
            for i, (label, body) in enumerate(bullets, start=1):
                lines.append(_format_bullet(i, label, body))

    utterances = _utterances_from_texts(lines)
    if not utterances:
        return _not_ready(typed_mode, "summary_not_ready", language)
    return ListenScript(mode=typed_mode, language=language, utterances=utterances)
