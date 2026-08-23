#!/usr/bin/env python3
"""Fail unless /health JSON matches lumina-core CHUNKER_VERSION and CORE_VERSION.

Used by scripts/build-release.sh sidecar smoke so HTTP 200 alone cannot ship
a binary whose handshake or app identity drifted from source.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_CHUNKER_RE = re.compile(r'^CHUNKER_VERSION\s*=\s*"([^"]+)"', re.M)
_CORE_RE = re.compile(r'^CORE_VERSION\s*=\s*"([^"]+)"', re.M)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_config_path() -> Path:
    return repo_root() / "packages" / "lumina-core" / "lumina_core" / "config.py"


def read_chunker_version(config_path: Path) -> str:
    text = config_path.read_text(encoding="utf-8")
    match = _CHUNKER_RE.search(text)
    if not match:
        raise ValueError(f"CHUNKER_VERSION not found in {config_path}")
    return match.group(1)


def read_core_version(config_path: Path) -> str:
    text = config_path.read_text(encoding="utf-8")
    match = _CORE_RE.search(text)
    if not match:
        raise ValueError(f"CORE_VERSION not found in {config_path}")
    return match.group(1)


def health_chunker_version(health: object) -> str:
    if not isinstance(health, dict):
        raise ValueError("/health JSON must be an object")
    value = health.get("chunker_version")
    if not isinstance(value, str) or not value:
        raise ValueError(f"/health missing string chunker_version: {health!r}")
    return value


def health_core_version(health: object) -> str:
    if not isinstance(health, dict):
        raise ValueError("/health JSON must be an object")
    value = health.get("core_version")
    if not isinstance(value, str) or not value:
        raise ValueError(f"/health missing string core_version: {health!r}")
    return value


def check_health_chunker_version(health: object, expected: str) -> str:
    got = health_chunker_version(health)
    if got != expected:
        raise ValueError(
            f"/health chunker_version={got!r} != CHUNKER_VERSION={expected!r}"
        )
    return got


def check_health_core_version(health: object, expected: str) -> str:
    got = health_core_version(health)
    if got != expected:
        raise ValueError(
            f"/health core_version={got!r} != CORE_VERSION={expected!r}"
        )
    return got


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=default_config_path(),
        help="Path to lumina_core/config.py",
    )
    args = parser.parse_args(argv)
    raw = sys.stdin.read()
    try:
        health = json.loads(raw)
        chunker = check_health_chunker_version(
            health, read_chunker_version(args.config)
        )
        core = check_health_core_version(health, read_core_version(args.config))
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        f"health chunker_version={chunker} core_version={core} "
        "matches lumina-core source"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
