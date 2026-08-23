"""Decode ingested text without requiring optional codecs like utf-8-sig."""

from __future__ import annotations

_UTF8_BOM = b"\xef\xbb\xbf"
# Never pass "utf-8-sig" to codecs: frozen sidecars may omit encodings.utf_8_sig
# and raise LookupError: unknown encoding: utf-8-sig. Strip a UTF-8 BOM ourselves.
_CANDIDATE_ENCODINGS = ("utf-8", "gb18030", "latin-1")


def _try_decode(data: bytes, encoding: str) -> str:
    return data.decode(encoding)


def decode_text_bytes(data: bytes) -> str:
    """Decode bytes from UTF-8 (with BOM), GB18030, or latin-1.

    Frozen sidecars may omit ``encodings.utf_8_sig``. A missing codec must not
    abort ingest or resegment before GB18030 (common for Chinese TXT) is tried.
    """
    if data.startswith(_UTF8_BOM):
        data = data[len(_UTF8_BOM) :]
    for encoding in _CANDIDATE_ENCODINGS:
        try:
            return _try_decode(data, encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")
