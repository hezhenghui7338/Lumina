"""Lightweight language normalization and translation need detection."""

from __future__ import annotations

import re
import unicodedata

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_KANA_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def normalize_lang(code: str | None) -> str | None:
    """Map locale codes to a coarse family (zh, en, ja, …)."""
    if not code or not str(code).strip():
        return None
    raw = str(code).strip().replace("_", "-").lower()
    primary = raw.split("-")[0]
    if primary in ("zh", "cmn"):
        return "zh"
    if primary in ("en",):
        return "en"
    if primary in ("ja",):
        return "ja"
    if primary in ("ko",):
        return "ko"
    if primary in ("fr",):
        return "fr"
    if primary in ("de",):
        return "de"
    if primary in ("es",):
        return "es"
    return primary


def languages_match(a: str | None, b: str | None) -> bool:
    na, nb = normalize_lang(a), normalize_lang(b)
    if na is None or nb is None:
        return False
    return na == nb


def infer_language(text: str) -> str | None:
    """Guess coarse language from character distribution (no external deps)."""
    sample = text[:4000]
    if not sample.strip():
        return None

    cjk = len(_CJK_RE.findall(sample))
    kana = len(_KANA_RE.findall(sample))
    latin = len(_LATIN_RE.findall(sample))
    letters = sum(
        1
        for ch in sample
        if unicodedata.category(ch).startswith("L") and not _CJK_RE.match(ch) and not _KANA_RE.match(ch)
    )
    total = cjk + kana + latin + letters
    if total < 20:
        return None

    if kana > cjk and kana >= latin:
        return "ja"
    if cjk >= latin and cjk / total >= 0.15:
        return "zh"
    if latin / total >= 0.5:
        return "en"
    if cjk > 0:
        return "zh"
    if latin > 0:
        return "en"
    return None


def book_needs_translation(
    *,
    book_language: str | None,
    book_target_language: str | None,
    global_target_language: str,
    text_sample: str | None = None,
) -> bool:
    """True when book language differs from the effective target language."""
    effective_target = book_target_language or global_target_language
    effective_book_lang = book_language
    if not effective_book_lang and text_sample:
        effective_book_lang = infer_language(text_sample)
    if not effective_book_lang or not effective_target:
        return False
    return not languages_match(effective_book_lang, effective_target)
