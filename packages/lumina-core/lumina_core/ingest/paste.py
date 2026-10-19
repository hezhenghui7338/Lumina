"""Turn pasted article text into one plain-text book."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

PASTE_MAX_BYTES = 15 * 1024 * 1024
PASTE_TITLE_MAX_CHARS = 80


class PasteImportError(Exception):
    """User-facing failure for pasted text that cannot become a book."""


@dataclass(frozen=True)
class PastedText:
    text: str
    title: str
    digest: str


def prepare_pasted_text(raw: str) -> PastedText:
    """Normalize one paste. Raises PasteImportError when it cannot be stored."""
    normalized = (raw or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise PasteImportError("没有可导入的正文")
    encoded = normalized.encode("utf-8")
    if len(encoded) > PASTE_MAX_BYTES:
        raise PasteImportError("文本超过 15MB，请改用 TXT 文件导入")
    first_line = normalized.split("\n", 1)[0].strip()
    title = first_line[:PASTE_TITLE_MAX_CHARS] or "未命名"
    digest = hashlib.sha256(encoded).hexdigest()
    return PastedText(text=normalized, title=title, digest=digest)


def write_pasted_text(dest: Path, text: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
