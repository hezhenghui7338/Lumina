"""Detect TXT encoding from a byte sample, then decode (including incrementally).

UTF-8 succeeding is not proof the file was meant as UTF-8: GBK mis-decoded as
Latin-1 and re-saved as UTF-8 is still valid UTF-8 (¡¡¡¡Ë«·½…). Never treat
latin-1 as a successful guess for Chinese prose.

Shift-JIS / CP932 Japanese often decodes as "valid" GB18030 into Han garbage with
no kana. Score CP932 / GB18030 / Big5 together (punctuation + kana + Han).

GBK/UTF-8/CP932 novels may still contain illegal bytes (converter junk). Strict
decode of the 64KiB sample then fails the whole book; score replace-decoded
CJK prose instead, and decode with errors='replace'.
"""

from __future__ import annotations

import codecs
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

_UTF8_BOM = b"\xef\xbb\xbf"
_UTF16_LE_BOM = b"\xff\xfe"
_UTF16_BE_BOM = b"\xfe\xff"
# Never pass "utf-8-sig" to codecs: frozen sidecars may omit encodings.utf_8_sig.
_CANDIDATE_ENCODINGS = ("utf-8", "gb18030", "gbk", "big5", "cp932", "utf-16", "latin-1")
# Prefer cp932 over shift_jis: Windows Japanese covers vendor extensions common in TXT dumps.
_CJK_LEGACY_ENCODINGS = ("cp932", "gb18030", "big5")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_KANA_RE = re.compile(r"[\u3040-\u30ff]")
_LATIN1_SUPP_RE = re.compile(r"[\u00a0-\u00ff]")
_SAMPLE_BYTES = 64 * 1024
_SAMPLE_CHARS = 12_000
_DECODE_BLOCK = 64 * 1024

UNRECOGNIZED_ENCODING = "无法识别文本编码"


@dataclass(frozen=True)
class EncodingPlan:
    """How to turn file bytes into Unicode. Detection uses a prefix only."""

    encoding: str
    bom_len: int = 0
    recover_gbk_mojibake: bool = False
    label: str = "utf-8"


def _try_decode(data: bytes, encoding: str) -> str:
    return data.decode(encoding)


def _decode_prefix(data: bytes, encoding: str, *, errors: str = "strict") -> str | None:
    """Decode a detection sample. A cut mid-character is not a rejection."""
    if not data:
        return ""
    try:
        decoder = codecs.getincrementaldecoder(encoding)(errors)
    except LookupError:
        return None
    try:
        return decoder.decode(data, final=False)
    except (UnicodeDecodeError, UnicodeError):
        return None


def _cjk_prose_stats(text: str) -> tuple[int, int, int, int]:
    sample = text[:_SAMPLE_CHARS]
    cjk = len(_CJK_RE.findall(sample))
    kana = len(_KANA_RE.findall(sample))
    punct = sample.count("。") + sample.count("，") + sample.count("、")
    repl = sample.count("\ufffd")
    return cjk, kana, punct, repl


def _is_cjk_prose(cjk: int, punct: int) -> bool:
    return cjk >= 40 and punct >= 2


def _is_japanese_prose(kana: int, punct: int) -> bool:
    """Hiragana/katakana plus JP/CJK punctuation — Shift-JIS must beat GB18030 mojibake."""
    return kana >= 40 and punct >= 2


def _accept_cjk_stats(cjk: int, kana: int, punct: int) -> bool:
    if _is_japanese_prose(kana, punct) or _is_cjk_prose(cjk, punct):
        return True
    # Short titles (e.g. 「金阁寺」) after UTF-8 failed.
    return cjk >= 1


def _rank_key(cjk: int, kana: int, punct: int, repl: int) -> tuple[int, int, int, int]:
    """Punctuation first so Big5 prose beats GB18030 false-kana mojibake."""
    return (punct, kana, cjk, -repl)


def _lossy_prose_stats(text: str) -> tuple[int, int, int, int] | None:
    """Score replace-decoded text. Prefer the first window; fall back to the full prefix."""
    head = text[:_SAMPLE_CHARS]
    stats = _cjk_prose_stats(head)
    cjk, kana, punct, repl = stats
    if _accept_cjk_stats(cjk, kana, punct) and (kana >= 40 or punct >= 2 or cjk >= 40):
        return stats
    if head != text:
        stats = _cjk_prose_stats(text)
        cjk, kana, punct, repl = stats
        if _accept_cjk_stats(cjk, kana, punct) and (kana >= 40 or punct >= 2 or cjk >= 40):
            return stats
    return None


def _best_cjk_plan(
    sample: bytes,
    encodings: tuple[str, ...],
    *,
    errors: str = "strict",
) -> EncodingPlan | None:
    """Pick the legacy CJK codec whose decode looks most like real prose."""
    best: EncodingPlan | None = None
    best_score: tuple[int, int, int, int] | None = None
    for enc in encodings:
        text = _decode_prefix(sample, enc, errors=errors)
        if not text:
            continue
        cjk, kana, punct, repl = _cjk_prose_stats(text)
        if not _accept_cjk_stats(cjk, kana, punct):
            continue
        if errors == "replace":
            # Lossy path: require prose signal so binary junk does not win on raw CJK count.
            if not (_is_japanese_prose(kana, punct) or _is_cjk_prose(cjk, punct)):
                continue
        score = _rank_key(cjk, kana, punct, repl)
        if best_score is None or score > best_score:
            best_score = score
            best = EncodingPlan(enc, label=enc)
    return best


def _lossy_cjk_plan(sample: bytes) -> EncodingPlan | None:
    """GBK/UTF-8/CP932 ebooks often embed binary junk. Strict decode then fails the whole book."""
    ranked: list[tuple[tuple[int, int, int, int], EncodingPlan]] = []
    for enc in ("utf-8", *_CJK_LEGACY_ENCODINGS):
        text = _decode_prefix(sample, enc, errors="replace")
        if not text:
            continue
        stats = _lossy_prose_stats(text)
        if stats is None:
            continue
        ranked.append((_rank_key(*stats), EncodingPlan(enc, label=enc)))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]


def _scrub_decoded(text: str) -> str:
    """Drop NULs so SQLite / native strings do not truncate the book."""
    if "\x00" not in text:
        return text
    return text.replace("\x00", "")


def _cjk_count(text: str) -> int:
    return len(_CJK_RE.findall(text[:_SAMPLE_CHARS]))


def _looks_like_gbk_mojibake(text: str) -> bool:
    """GBK decoded as Latin-1/CP1252: almost no Han, many Latin-1 supplement chars."""
    sample = text[:_SAMPLE_CHARS]
    cjk = len(_CJK_RE.findall(sample))
    latin1 = len(_LATIN1_SUPP_RE.findall(sample))
    if latin1 < 24:
        return False
    return cjk * 5 < latin1


def _looks_like_cjk_prose(text: str) -> bool:
    cjk, _kana, punct, _repl = _cjk_prose_stats(text)
    return _is_cjk_prose(cjk, punct) or _is_japanese_prose(_kana, punct)


def _recover_sample(text: str) -> str | None:
    sample = text[:_SAMPLE_CHARS]
    for source in ("latin-1", "cp1252"):
        try:
            raw = sample.encode(source)
        except UnicodeEncodeError:
            continue
        for target in ("gb18030", "gbk", "cp936", "cp932"):
            try:
                recovered = raw.decode(target)
            except (UnicodeDecodeError, LookupError):
                continue
            if _looks_like_cjk_prose(recovered):
                return recovered
    return None


def _bom_plan(data: bytes) -> EncodingPlan | None:
    if data.startswith(_UTF8_BOM):
        return EncodingPlan("utf-8", bom_len=len(_UTF8_BOM), label="utf-8")
    if data.startswith(_UTF16_LE_BOM):
        return EncodingPlan("utf-16-le", bom_len=2, label="utf-16-le")
    if data.startswith(_UTF16_BE_BOM):
        return EncodingPlan("utf-16-be", bom_len=2, label="utf-16-be")
    return None


def _normalize_codec(name: str) -> str:
    key = name.lower().replace("-", "_")
    aliases = {
        "utf_8": "utf-8",
        "utf8": "utf-8",
        "gb18030": "gb18030",
        "gbk": "gb18030",
        "cp936": "gb18030",
        "gb2312": "gb18030",
        "big5": "big5",
        "big5hkscs": "big5",
        "shift_jis": "cp932",
        "shift_jis_2004": "cp932",
        "shift_jisx0213": "cp932",
        "csshiftjis": "cp932",
        "sjis": "cp932",
        "cp932": "cp932",
        "ms932": "cp932",
        "windows_31j": "cp932",
        "utf_16": "utf-16",
        "utf_16_le": "utf-16-le",
        "utf_16_be": "utf-16-be",
        "latin_1": "latin-1",
        "iso8859_1": "latin-1",
        "iso_8859_1": "latin-1",
        "cp1252": "cp1252",
        "windows_1252": "cp1252",
    }
    return aliases.get(key, name.lower())


def detect_encoding_plan(data: bytes) -> EncodingPlan:
    """Identify encoding from a prefix. Does not decode the rest of the file."""
    if not data:
        return EncodingPlan("utf-8", label="utf-8")
    bom = _bom_plan(data)
    if bom is not None:
        return bom
    sample = data[:_SAMPLE_BYTES]
    utf8 = _decode_prefix(sample, "utf-8")
    if utf8 is not None:
        if _looks_like_gbk_mojibake(utf8) and _recover_sample(utf8) is not None:
            return EncodingPlan(
                "utf-8",
                recover_gbk_mojibake=True,
                label="utf-8-gbk-mojibake",
            )
        return EncodingPlan("utf-8", label="utf-8")

    # After UTF-8 fails: score CP932 / GB18030 / Big5 together. Shift-JIS Japanese
    # bytes often "succeed" as GB18030 into Han garbage with zero kana — never pick
    # that over a decode that has real ひらがな/カタカナ + 。、.
    legacy = _best_cjk_plan(sample, _CJK_LEGACY_ENCODINGS)
    if legacy is not None:
        return legacy

    lossy = _lossy_cjk_plan(sample)
    if lossy is not None:
        return lossy

    try:
        from charset_normalizer import from_bytes

        best = from_bytes(sample).best()
    except Exception:
        best = None
    if best is not None and best.encoding:
        enc = _normalize_codec(str(best.encoding))
        if enc in {"latin-1", "cp1252"}:
            legacy = _best_cjk_plan(sample, _CJK_LEGACY_ENCODINGS)
            if legacy is not None:
                return legacy
            return EncodingPlan(enc, label=enc)
        if enc in {
            "gb18030",
            "big5",
            "cp932",
            "utf-8",
            "utf-16",
            "utf-16-le",
            "utf-16-be",
        }:
            return EncodingPlan(enc, label=enc)
        legacy = _best_cjk_plan(sample, _CJK_LEGACY_ENCODINGS)
        if legacy is not None:
            return legacy
        if _decode_prefix(sample, enc) is not None:
            return EncodingPlan(enc, label=enc)

    raise ValueError(UNRECOGNIZED_ENCODING)


class IncrementalTextDecoder:
    """Incremental Unicode decoder matching an EncodingPlan."""

    def __init__(self, plan: EncodingPlan) -> None:
        self.plan = plan
        if plan.recover_gbk_mojibake:
            self._utf8 = codecs.getincrementaldecoder("utf-8")()
            self._gb = codecs.getincrementaldecoder("gb18030")("replace")
            self._direct = None
        else:
            self._direct = codecs.getincrementaldecoder(plan.encoding)("replace")
            self._utf8 = None
            self._gb = None

    def feed(self, data: bytes, *, final: bool = False) -> str:
        if not data and not final:
            return ""
        if self.plan.recover_gbk_mojibake:
            assert self._utf8 is not None and self._gb is not None
            moji = self._utf8.decode(data, final=final)
            if not moji and not final:
                return ""
            try:
                raw = moji.encode("latin-1")
            except UnicodeEncodeError:
                raw = moji.encode("cp1252")
            return _scrub_decoded(self._gb.decode(raw, final=final))
        assert self._direct is not None
        return _scrub_decoded(self._direct.decode(data, final=final))


def iter_decoded_file(
    path: Path,
    *,
    plan: EncodingPlan | None = None,
    block_size: int = _DECODE_BLOCK,
    on_bytes: Callable[[int, int], None] | None = None,
) -> Iterator[str]:
    """Yield decoded Unicode chunks without loading the whole file."""
    try:
        file_size = path.stat().st_size
    except OSError:
        file_size = 0
    with path.open("rb") as handle:
        leftover = b""
        if plan is None:
            sample = handle.read(_SAMPLE_BYTES)
            plan = detect_encoding_plan(sample)
            leftover = sample[plan.bom_len :]
        elif plan.bom_len:
            handle.read(plan.bom_len)
        decoder = IncrementalTextDecoder(plan)

        def _note() -> None:
            if on_bytes is not None:
                on_bytes(handle.tell(), file_size)

        if leftover:
            piece = decoder.feed(leftover)
            _note()
            if piece:
                yield piece
        while True:
            block = handle.read(block_size)
            if not block:
                piece = decoder.feed(b"", final=True)
                _note()
                if piece:
                    yield piece
                return
            piece = decoder.feed(block)
            _note()
            if piece:
                yield piece


def decode_text_bytes(data: bytes) -> str:
    """Decode a complete in-memory buffer (HTML/FB2/tests). Prefer iter_decoded_file for TXT."""
    plan = detect_encoding_plan(data)
    decoder = IncrementalTextDecoder(plan)
    return decoder.feed(data[plan.bom_len :], final=True)
