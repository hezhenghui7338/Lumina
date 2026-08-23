"""RTF ingestion via striprtf."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def _metadata_value(source: str, field: str) -> str | None:
    match = re.search(rf"\\{field}\s+((?:\\[{{}}]|[^{{}}])*)\}}", source, re.IGNORECASE)
    if not match:
        return None
    value = match.group(1)
    value = value.replace(r"\{", "{").replace(r"\}", "}").replace(r"\\", "\\")
    value = re.sub(r"\\'[0-9a-fA-F]{2}", "", value)
    value = re.sub(r"\\[a-zA-Z]+-?\d*\s?", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def load_rtf(path: Path) -> tuple[str, dict[str, Any]]:
    try:
        from striprtf.striprtf import rtf_to_text
    except ImportError as exc:
        raise RuntimeError("RTF support requires striprtf: pip install striprtf") from exc

    try:
        source = path.read_text(encoding="latin-1")
        if not source.lstrip().startswith(r"{\rtf"):
            raise ValueError("Invalid RTF document")
        text = rtf_to_text(source, errors="ignore").strip()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Unable to parse RTF document") from exc

    if not text:
        raise ValueError("RTF document contains no readable text")
    metadata = {
        key: value
        for key in ("title", "author")
        if (value := _metadata_value(source, key))
    }
    return text, metadata
