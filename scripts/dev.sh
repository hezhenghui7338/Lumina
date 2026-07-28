#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/packages/lumina-core"
uv sync --extra dev 2>/dev/null || pip install -e ".[dev]"
uv run lumina-core --host 127.0.0.1 --port 17432
