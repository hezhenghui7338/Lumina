"""Tests for OpenAI-compatible API URL resolution."""

from __future__ import annotations

import httpx

from lumina_core.models.openai_compat import (
    openai_compat_client_base,
    openai_compat_completions_url,
    openai_compat_paths,
)


def _joined(base_url: str, rel_path: str) -> str:
    return str(httpx.URL(openai_compat_client_base(base_url)).join(rel_path))


URL_CASES = [
    (
        "https://openrouter.ai/api/v1",
        "https://openrouter.ai/api/v1/models",
        "https://openrouter.ai/api/v1/chat/completions",
    ),
    (
        "https://api.openai.com/v1",
        "https://api.openai.com/v1/models",
        "https://api.openai.com/v1/chat/completions",
    ),
    (
        "https://proxy.example/v1",
        "https://proxy.example/v1/models",
        "https://proxy.example/v1/chat/completions",
    ),
    (
        "https://aiping.cn/api/v1",
        "https://aiping.cn/api/v1/models",
        "https://aiping.cn/api/v1/chat/completions",
    ),
    (
        "https://custom.example",
        "https://custom.example/v1/models",
        "https://custom.example/v1/chat/completions",
    ),
]


def test_openai_compat_client_base_trailing_slash():
    assert openai_compat_client_base("https://openrouter.ai/api/v1") == (
        "https://openrouter.ai/api/v1/"
    )
    assert openai_compat_client_base("https://openrouter.ai/api/v1/") == (
        "https://openrouter.ai/api/v1/"
    )


def test_openai_compat_paths():
    assert openai_compat_paths("https://openrouter.ai/api/v1") == (
        "models",
        "chat/completions",
    )
    assert openai_compat_paths("https://api.openai.com/v1") == (
        "models",
        "chat/completions",
    )
    assert openai_compat_paths("https://custom.example") == (
        "v1/models",
        "v1/chat/completions",
    )


def test_openai_compat_resolved_urls():
    for base_url, models_url, completions_url in URL_CASES:
        models_path, completions_path = openai_compat_paths(base_url)
        assert _joined(base_url, models_path) == models_url
        assert _joined(base_url, completions_path) == completions_url
        assert openai_compat_completions_url(base_url) == completions_url
