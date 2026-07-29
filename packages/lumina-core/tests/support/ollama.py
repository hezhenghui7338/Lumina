"""Ollama availability helpers."""

from __future__ import annotations

import httpx

from lumina_core.config import LUMINA_SUMMARIZE_MODEL, OLLAMA_BASE_URL
from lumina_core.ollama_setup import is_local_base_url


def ollama_available(base_url: str = OLLAMA_BASE_URL) -> bool:
    try:
        resp = httpx.get(
            f"{base_url.rstrip('/')}/api/tags",
            timeout=2.0,
            trust_env=not is_local_base_url(base_url),
        )
        if resp.status_code != 200:
            return False
        models = [m.get("name", "") for m in resp.json().get("models", [])]
        target = LUMINA_SUMMARIZE_MODEL.split(":")[0]
        return any(target in name for name in models)
    except (httpx.HTTPError, OSError):
        return False
