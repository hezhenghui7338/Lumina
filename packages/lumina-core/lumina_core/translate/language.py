"""Lightweight language normalization and translation need detection."""

from __future__ import annotations

import re
import unicodedata

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_KANA_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_KANA_RUN = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]{2,}")
_CYRILLIC_RUN = re.compile(r"[\u0400-\u04ff]{2,}")
_HANGUL_RUN = re.compile(r"[\uac00-\ud7af]{2,}")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]{4,}")
_LATIN_WORD_RUN = re.compile(
    r"[A-Za-z]{2,}(?:['’][A-Za-z]+)?(?:[\s,;:\"“”‘’()-]+[A-Za-z]{2,}(?:['’][A-Za-z]+)?)+"
)
# CJK glued to ≥4 ASCII letters (海BuilderInterface / 未知lendary世界).
_CJK_LATIN_GLUE = re.compile(
    r"(?:[\u4e00-\u9fff][A-Za-z]{4,})|(?:[A-Za-z]{4,}[\u4e00-\u9fff])"
)
# Programming-style CamelCase (BuilderInterface); ChatGPT does not match.
_CAMEL_IDENT = re.compile(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+){1,}\b")
# Lowercase English token ≥6 in mixed CJK context (failed / lendary).
_LOWER_LATIN_WORD = re.compile(r"(?<![A-Za-z])[a-z]{6,}(?![A-Za-z])")
# Latin Extended / Vietnamese tone letters (ộ, ạ, …).
_EXTENDED_LATIN_WORD = re.compile(
    r"[A-Za-z]*[\u00c0-\u024f\u1e00-\u1eff][A-Za-z\u00c0-\u024f\u1e00-\u1eff]*"
)
_SHORT_PROPER_MAX = 12
_EN_FUNCTION_WORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "to",
        "of",
        "and",
        "in",
        "that",
        "this",
        "these",
        "those",
        "for",
        "with",
        "on",
        "as",
        "at",
        "by",
        "from",
        "or",
        "it",
        "he",
        "she",
        "they",
        "we",
        "you",
        "not",
        "but",
        "if",
        "then",
        "than",
        "after",
        "before",
        "into",
        "about",
        "along",
        "across",
        "over",
        "under",
        "out",
        "up",
        "down",
        "off",
    }
)


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


_DISPLAY_NAMES = {
    "en": "English",
    "ja": "日本語",
    "ko": "한국어",
    "fr": "Français",
    "de": "Deutsch",
    "es": "Español",
    "ru": "Русский",
}


def language_display_name(code: str | None) -> str:
    """Human-readable name for prompt injection (never a bare locale code)."""
    family = normalize_lang(code)
    if family == "zh":
        raw = (code or "").strip().replace("_", "-").lower()
        if raw.startswith(("zh-tw", "zh-hk", "zh-hant")) or "hant" in raw:
            return "繁体中文"
        return "简体中文"
    if family and family in _DISPLAY_NAMES:
        return _DISPLAY_NAMES[family]
    stripped = (code or "").strip()
    return stripped or "简体中文"


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


def _allow_short_source_term(span: str, source_text: str | None) -> bool:
    if not source_text or len(span) > _SHORT_PROPER_MAX:
        return False
    return span in source_text


def _latin_core(span: str) -> str:
    """Extract the longest ASCII-letter run from a mixed glue span."""
    runs = re.findall(r"[A-Za-z]+", span)
    return max(runs, key=len) if runs else span


def _allow_latin_in_source(span: str, source_text: str | None) -> bool:
    """Allow short proper names that appear in the source (full span or Latin core)."""
    if _allow_short_source_term(span, source_text):
        return True
    core = _latin_core(span)
    if core != span and _allow_short_source_term(core, source_text):
        return True
    return False


def _english_clause_span(text: str) -> tuple[int, str] | None:
    for match in _LATIN_WORD_RUN.finditer(text):
        tokens = re.findall(r"[A-Za-z]{2,}", match.group())
        # ≥3 Latin words, or ≥2 with a function word (along the line).
        if len(tokens) >= 3 or (
            len(tokens) >= 2 and any(token.lower() in _EN_FUNCTION_WORDS for token in tokens)
        ):
            return match.start(), match.group().strip()[:60]
    return None


def _cjk_latin_mix_span(
    text: str, *, source_text: str | None
) -> tuple[int, str, str] | None:
    """Flag CJK↔Latin glue, CamelCase ids, extended Latin, and stray lowercase tokens."""
    for match in _CJK_LATIN_GLUE.finditer(text):
        span = match.group()
        if _allow_latin_in_source(span, source_text):
            continue
        return match.start(), span[:40], "汉字与拉丁词粘连"

    for match in _CAMEL_IDENT.finditer(text):
        span = match.group()
        if _allow_latin_in_source(span, source_text):
            continue
        return match.start(), span[:40], "夹杂程序标识符式英文"

    for match in _EXTENDED_LATIN_WORD.finditer(text):
        span = match.group()
        if _allow_latin_in_source(span, source_text):
            continue
        return match.start(), span[:40], "夹杂带调拉丁字母"

    if _CJK_RE.search(text):
        for match in _LOWER_LATIN_WORD.finditer(text):
            span = match.group()
            if _allow_latin_in_source(span, source_text):
                continue
            return match.start(), span[:40], "夹杂英语碎片"
    return None


def unexpected_language_span(
    text: str,
    *,
    target_language: str | None,
    source_text: str | None = None,
) -> tuple[int, str, str] | None:
    """Return (start, snippet, problem) when summary text mixes unexpected scripts."""
    family = normalize_lang(target_language) or "zh"
    stripped = (text or "").strip()
    if not stripped:
        return None

    def _flag_run(pattern: re.Pattern[str], problem: str) -> tuple[int, str, str] | None:
        for match in pattern.finditer(text):
            span = match.group()
            if _allow_short_source_term(span, source_text):
                continue
            return match.start(), span[:40], problem
        return None

    if family != "ja":
        hit = _flag_run(_KANA_RUN, "夹杂日语假名")
        if hit:
            return hit
    hit = _flag_run(_CYRILLIC_RUN, "夹杂西里尔字母")
    if hit:
        return hit
    if family != "ko":
        hit = _flag_run(_HANGUL_RUN, "夹杂韩文")
        if hit:
            return hit
    if family == "en":
        hit = _flag_run(_CJK_RUN, "夹杂汉字整段")
        if hit:
            return hit
        return None

    if family in {"zh", "ja", "ko"}:
        mix = _cjk_latin_mix_span(text, source_text=source_text)
        if mix is not None:
            return mix
        clause = _english_clause_span(text)
        if clause is not None:
            start, snippet = clause
            if not _allow_latin_in_source(snippet, source_text):
                return start, snippet, "夹杂英语整句"
        latin = len(_LATIN_RE.findall(text))
        cjk = len(_CJK_RE.findall(text))
        kana = len(_KANA_RE.findall(text))
        letters = latin + cjk + kana
        if latin >= 24 and letters and latin / letters > 0.45:
            return 0, stripped[:40], "正文以英语为主"
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
