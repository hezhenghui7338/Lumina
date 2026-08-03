"""Mock LLM router for deterministic tests."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal

Profile = Literal["chat", "summarize", "translate"]


from lumina_core.config import ModelsConfig


class MockModelRouter:
    def __init__(
        self,
        responses: dict[str, Any] | None = None,
        models: ModelsConfig | None = None,
    ) -> None:
        self.responses = responses or {}
        self.calls: list[dict[str, Any]] = []
        self.models = models or ModelsConfig()
        self.last_resource_id: str | None = "ollama"
        self.last_provider: str | None = "ollama"
        self.last_model: str | None = self.models.resource_by_id("ollama").model if self.models.resource_by_id("ollama") else "qwen3.5:4b"
        self.last_usage: dict[str, int] | None = {
            "prompt_tokens": 120,
            "completion_tokens": 40,
            "total_tokens": 160,
        }
        self.last_duration_ms: int | None = 800
        self.last_tps: float | None = 50.0

    def set_response(self, profile: Profile, value: Any) -> None:
        self.responses[profile] = value

    def chat_metrics(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.last_provider:
            out["provider"] = self.last_provider
        if self.last_model:
            out["model"] = self.last_model
        if self.last_duration_ms is not None:
            out["duration_ms"] = self.last_duration_ms
        if self.last_usage:
            out.update(self.last_usage)
        if self.last_tps is not None:
            out["tps"] = self.last_tps
        return out

    async def complete(
        self,
        prompt: str,
        *,
        profile: Profile = "summarize",
        json_mode: bool = False,
        on_slot_acquired=None,
    ) -> str:
        if on_slot_acquired is not None:
            await on_slot_acquired()
        self.calls.append({"method": "complete", "profile": profile, "prompt": prompt})
        raw = self.responses.get(profile, self.responses.get("summarize", "{}"))
        if isinstance(raw, (dict, list)):
            return json.dumps(raw, ensure_ascii=False)
        return str(raw)

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        profile: Profile = "chat",
        stream: bool = False,
        json_mode: bool = False,
    ) -> str | AsyncIterator[str]:
        self.calls.append({"method": "chat", "profile": profile, "messages": messages, "stream": stream})
        raw = self.responses.get(profile, self.responses.get("chat", "{}"))
        if isinstance(raw, (dict, list)):
            text = json.dumps(raw, ensure_ascii=False)
        else:
            text = str(raw)

        if stream:
            async def _gen():
                yield text

            return _gen()
        return text

    async def aclose(self) -> None:
        return None

    def update_resources(self, resources) -> None:
        return None


def load_json_fixture(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
