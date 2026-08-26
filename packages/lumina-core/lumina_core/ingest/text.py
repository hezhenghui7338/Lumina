"""Detect TXT encoding from a byte sample, then decode (including incrementally).

UTF-8 succeeding is not proof the file was meant as UTF-8: GBK mis-decoded as
Latin-1 and re-saved as UTF-8 is still valid UTF-8 (¡¡¡¡Ë«·½…). Never treat
latin-1 as a successful guess for Chinese prose.
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
_CANDIDATE_ENCODINGS = ("utf-8", "gb18030", "gbk", "big5", "utf-16", "latin-1")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
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


def _decode_prefix(data: bytes, encoding: str) -> str | None:
    """Decode a detection sample. A cut mid-character is not a rejection."""
    if not data:
        return ""
    try:
        decoder = codecs.getincrementaldecoder(encoding)()
    except LookupError:
        return None
    try:
        return decoder.decode(data, final=False)
    except (UnicodeDecodeError, UnicodeError):
        return None


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
    sample = text[:_SAMPLE_CHARS]
    cjk = len(_CJK_RE.findall(sample))
    punct = sample.count("。") + sample.count("，") + sample.count("、")
    return cjk >= 40 and punct >= 2


def _recover_sample(text: str) -> str | None:
    sample = text[:_SAMPLE_CHARS]
    for source in ("latin-1", "cp1252"):
        try:
            raw = sample.encode(source)
        except UnicodeEncodeError:
            continue
        for target in ("gb18030", "gbk", "cp936"):
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


def _gb18030_if_cjk(sample: bytes) -> EncodingPlan | None:
    text = _decode_prefix(sample, "gb18030")
    if text is None:
        return None
    # UTF-8 already failed. Any Han is enough — titles like 「金阁寺」 are short.
    if _cjk_count(text) >= 1:
        return EncodingPlan("gb18030", label="gb18030")
    return None


def _big5_if_cjk(sample: bytes) -> EncodingPlan | None:
    text = _decode_prefix(sample, "big5")
    if text is None:
        return None
    if _cjk_count(text) >= 1:
        return EncodingPlan("big5", label="big5")
    return None


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

    gb = _gb18030_if_cjk(sample)
    big5 = _big5_if_cjk(sample)
    if gb is not None and big5 is not None:
        gb_n = _cjk_count(_decode_prefix(sample, "gb18030") or "")
        big5_n = _cjk_count(_decode_prefix(sample, "big5") or "")
        return gb if gb_n >= big5_n else big5
    if gb is not None:
        return gb
    if big5 is not None:
        return big5

    try:
        from charset_normalizer import from_bytes

        best = from_bytes(sample).best()
    except Exception:
        best = None
    if best is not None and best.encoding:
        enc = _normalize_codec(str(best.encoding))
        if enc in {"latin-1", "cp1252"}:
            gb = _gb18030_if_cjk(sample)
            if gb is not None:
                return gb
            return EncodingPlan(enc, label=enc)
        if enc in {"gb18030", "big5", "utf-8", "utf-16", "utf-16-le", "utf-16-be"}:
            return EncodingPlan(enc, label=enc)
        gb = _gb18030_if_cjk(sample)
        if gb is not None:
            return gb
        if _decode_prefix(sample, enc) is not None:
            return EncodingPlan(enc, label=enc)

    raise ValueError(UNRECOGNIZED_ENCODING)


class IncrementalTextDecoder:
    """Incremental Unicode decoder matching an EncodingPlan."""

    def __init__(self, plan: EncodingPlan) -> None:
        self.plan = plan
        if plan.recover_gbk_mojibake:
            self._utf8 = codecs.getincrementaldecoder("utf-8")()
            self._gb = codecs.getincrementaldecoder("gb18030")()
            self._direct = None
        else:
            self._direct = codecs.getincrementaldecoder(plan.encoding)()
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
            return self._gb.decode(raw, final=final)
        assert self._direct is not None
        return self._direct.decode(data, final=final)


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
