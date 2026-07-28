"""Hardware detection — reference LocalAgent hardware.py."""

from __future__ import annotations

import platform
import re
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelTier:
    min_ram_bytes: int
    model: str
    size_hint: str
    label: str


MODEL_TIERS: tuple[ModelTier, ...] = (
    ModelTier(0, "qwen3.5:0.8b", "~1.0 GB", "Mini"),
    ModelTier(6 * (1024**3), "qwen3.5:2b", "~2.7 GB", "轻量"),
    ModelTier(10 * (1024**3), "qwen3.5:4b", "~3.4 GB", "推荐"),
    ModelTier(18 * (1024**3), "qwen3.5:9b", "~6.6 GB", "高配"),
)

DEFAULT_TIER_MODEL = "qwen3.5:4b"


def total_ram_bytes() -> int | None:
    system = platform.system()
    try:
        if system == "Darwin":
            out = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
                check=False,
            )
            if out.returncode == 0 and (out.stdout or "").strip().isdigit():
                return int(out.stdout.strip())
        if system == "Linux":
            text = open("/proc/meminfo", encoding="utf-8").read()  # noqa: SIM115
            match = re.search(r"^MemTotal:\s+(\d+)\s+kB", text, re.MULTILINE)
            if match:
                return int(match.group(1)) * 1024
    except Exception:
        return None
    return None


def recommend_ollama_model(ram_bytes: int | None = None) -> str:
    ram = ram_bytes if ram_bytes is not None else total_ram_bytes()
    if ram is None:
        return DEFAULT_TIER_MODEL
    chosen = MODEL_TIERS[0]
    for tier in MODEL_TIERS:
        if ram >= tier.min_ram_bytes:
            chosen = tier
    return chosen.model


def format_ram_gb(ram_bytes: int | None) -> str:
    if ram_bytes is None:
        return "unknown"
    return f"{ram_bytes / (1024**3):.1f} GB"
