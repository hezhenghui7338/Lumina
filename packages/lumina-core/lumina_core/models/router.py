"""Three-profile model router."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any, Literal

import httpx

from lumina_core.config import ModelsConfig, ProfileConfig

Profile = Literal["chat", "summarize", "translate"]

_router: ProfileModelRouter | None = None


class ProfileModelRouter:
    """Route LLM calls to chat / summarize / translate profiles."""

    def __init__(self, models: ModelsConfig) -> None:
        self.models = models
        self._clients: dict[str, httpx.AsyncClient] = {}

    def _profile_cfg(self, profile: Profile) -> ProfileConfig:
        return getattr(self.models, profile)

    def _client_for(self, cfg: ProfileConfig) -> httpx.AsyncClient:
        key = cfg.base_url
        if key not in self._clients:
            headers: dict[str, str] = {}
            if cfg.api_key:
                headers["Authorization"] = f"Bearer {cfg.api_key}"
            self._clients[key] = httpx.AsyncClient(
                base_url=cfg.base_url.rstrip("/"),
                headers=headers,
                timeout=120.0,
            )
        return self._clients[key]

    async def complete(
        self,
        prompt: str,
        *,
        profile: Profile = "summarize",
        json_mode: bool = False,
    ) -> str:
        cfg = self._profile_cfg(profile)
        if cfg.provider == "ollama":
            return await self._ollama_complete(cfg, prompt, json_mode=json_mode)
        return await self._openai_complete(cfg, prompt, json_mode=json_mode)

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        profile: Profile = "chat",
        stream: bool = False,
        json_mode: bool = False,
    ) -> str | AsyncIterator[str]:
        cfg = self._profile_cfg(profile)
        if stream:
            if cfg.provider == "ollama":
                return self._ollama_chat_stream(cfg, messages, json_mode=json_mode)
            return self._openai_chat_stream(cfg, messages, json_mode=json_mode)
        if cfg.provider == "ollama":
            return await self._ollama_chat(cfg, messages, json_mode=json_mode)
        return await self._openai_chat(cfg, messages, json_mode=json_mode)

    async def _ollama_complete(
        self, cfg: ProfileConfig, prompt: str, *, json_mode: bool
    ) -> str:
        client = self._client_for(cfg)
        payload: dict[str, Any] = {
            "model": cfg.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        if json_mode:
            payload["format"] = "json"
        resp = await client.post("/api/chat", json=payload)
        resp.raise_for_status()
        return resp.json()["message"]["content"]

    async def _ollama_chat(
        self, cfg: ProfileConfig, messages: list[dict[str, str]], *, json_mode: bool
    ) -> str:
        client = self._client_for(cfg)
        payload: dict[str, Any] = {
            "model": cfg.model,
            "messages": messages,
            "stream": False,
        }
        if json_mode:
            payload["format"] = "json"
        resp = await client.post("/api/chat", json=payload)
        resp.raise_for_status()
        return resp.json()["message"]["content"]

    async def _ollama_chat_stream(
        self, cfg: ProfileConfig, messages: list[dict[str, str]], *, json_mode: bool
    ) -> AsyncIterator[str]:
        client = self._client_for(cfg)
        payload: dict[str, Any] = {
            "model": cfg.model,
            "messages": messages,
            "stream": True,
        }
        if json_mode:
            payload["format"] = "json"
        async with client.stream("POST", "/api/chat", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                data = json.loads(line)
                chunk = data.get("message", {}).get("content", "")
                if chunk:
                    yield chunk

    async def _openai_complete(
        self, cfg: ProfileConfig, prompt: str, *, json_mode: bool
    ) -> str:
        client = self._client_for(cfg)
        payload: dict[str, Any] = {
            "model": cfg.model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        resp = await client.post("/v1/chat/completions", json=payload)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    async def _openai_chat(
        self, cfg: ProfileConfig, messages: list[dict[str, str]], *, json_mode: bool
    ) -> str:
        client = self._client_for(cfg)
        payload: dict[str, Any] = {"model": cfg.model, "messages": messages}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        resp = await client.post("/v1/chat/completions", json=payload)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    async def _openai_chat_stream(
        self, cfg: ProfileConfig, messages: list[dict[str, str]], *, json_mode: bool
    ) -> AsyncIterator[str]:
        client = self._client_for(cfg)
        payload: dict[str, Any] = {
            "model": cfg.model,
            "messages": messages,
            "stream": True,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        async with client.stream("POST", "/v1/chat/completions", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if data_str == "[DONE]":
                    break
                data = json.loads(data_str)
                delta = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                if delta:
                    yield delta

    async def aclose(self) -> None:
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()


class OllamaRouter(ProfileModelRouter):
    """Backward-compatible alias for tests."""

    def __init__(
        self,
        base_url: str,
        models: dict[Profile, str] | None = None,
    ) -> None:
        from lumina_core.config import ModelsConfig, ProfileConfig

        m = models or {"summarize": "qwen3.5:4b", "chat": "qwen3.5:4b", "translate": "qwen3.5:4b"}
        cfg = ModelsConfig(
            chat=ProfileConfig(base_url=base_url, model=m["chat"]),
            summarize=ProfileConfig(base_url=base_url, model=m["summarize"]),
            translate=ProfileConfig(base_url=base_url, model=m["translate"]),
        )
        super().__init__(cfg)


def get_router() -> ProfileModelRouter:
    if _router is None:
        raise RuntimeError("ModelRouter not configured; call set_router() first")
    return _router


def set_router(router: ProfileModelRouter | OllamaRouter | Any | None) -> None:
    global _router
    _router = router  # type: ignore[assignment]


def parse_json_response(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise
