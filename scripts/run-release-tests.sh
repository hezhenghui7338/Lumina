#!/usr/bin/env bash
# Release test gate: mock suite only (parallel).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CORE_PKG="$ROOT/packages/lumina-core"

cd "$CORE_PKG"
uv sync --extra dev --extra release

echo "==> Release tests (mock only, parallel)…"
uv run pytest \
  -m "not live and not live_chunk and not release_live and not perf" \
  -n auto --dist loadscope -q
