"""OpenAI-compatible API URL helpers for httpx base_url + relative path joining."""

from __future__ import annotations


def openai_compat_client_base(base_url: str) -> str:
    """Return httpx base_url with trailing slash for safe relative path joins."""
    return base_url.strip().rstrip("/") + "/"


def openai_compat_paths(base_url: str) -> tuple[str, str]:
    """Return (models_path, completions_path) relative to client base_url."""
    if base_url.rstrip("/").endswith("/v1"):
        return "models", "chat/completions"
    return "v1/models", "v1/chat/completions"


def openai_compat_completions_url(base_url: str) -> str:
    """Resolve the full chat/completions URL for a configured base_url."""
    import httpx

    client_base = openai_compat_client_base(base_url)
    _, completions_path = openai_compat_paths(base_url)
    return str(httpx.URL(client_base).join(completions_path))
