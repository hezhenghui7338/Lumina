"""Ollama setup — reference LocalAgent ollama_setup.py (subset)."""

from __future__ import annotations

import shutil
from dataclasses import dataclass

import httpx

from lumina_core.hardware import format_ram_gb, recommend_ollama_model, total_ram_bytes


@dataclass(frozen=True)
class OllamaStatus:
    installed: bool
    served: bool
    model: str
    model_ready: bool
    ram_gb: str
    message: str = ""


def ollama_bin() -> str | None:
    return shutil.which("ollama")


async def check_ollama_status(
    base_url: str = "http://localhost:11434",
    model: str | None = None,
) -> OllamaStatus:
    ram = total_ram_bytes()
    recommended = model or recommend_ollama_model(ram)
    installed = ollama_bin() is not None
    served = False
    model_ready = False
    message = ""

    if not installed:
        return OllamaStatus(
            installed=False,
            served=False,
            model=recommended,
            model_ready=False,
            ram_gb=format_ram_gb(ram),
            message="Ollama not installed",
        )

    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=5.0) as client:
            resp = await client.get("/api/tags")
            served = resp.status_code == 200
            if served:
                names = {m.get("name", "") for m in resp.json().get("models", [])}
                model_ready = any(
                    recommended in n or n.startswith(recommended.split(":")[0])
                    for n in names
                )
    except httpx.HTTPError:
        message = "Ollama installed but server unreachable"

    return OllamaStatus(
        installed=installed,
        served=served,
        model=recommended,
        model_ready=model_ready,
        ram_gb=format_ram_gb(ram),
        message=message,
    )
