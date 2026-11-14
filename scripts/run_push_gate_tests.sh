#!/usr/bin/env bash
# Commit / push gate: mock pytest only (same marker set as `just test`).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/packages/lumina-core"
exec uv run pytest -m "not live and not live_chunk and not release_live and not perf" -q
