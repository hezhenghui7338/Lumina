"""Mock LLM router for deterministic tests."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal

Profile = Literal["chat", "summarize", "translate"]


class MockModelRouter:
    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[dict[str, Any]] = []

    def set_response(self, profile: Profile, value: Any) -> None:
        self.responses[profile] = value

    async def complete(
        self,
        prompt: str,
        *,
        profile: Profile = "summarize",
        json_mode: bool = False,
    ) -> str:
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


def load_json_fixture(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
