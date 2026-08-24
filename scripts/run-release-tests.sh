#!/usr/bin/env bash
# Release test gate: mock suite only (parallel).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CORE_PKG="$ROOT/packages/lumina-core"

# Runner default CPython (3.14 on macos-15) inflates the PyInstaller sidecar
# past the 500MB Lumina.app cap. Release must follow the repo pin.
export UV_PYTHON="${UV_PYTHON:-$(tr -d '[:space:]' < "$ROOT/.python-version")}"

echo "==> Bad case catalog gate…"
python3 "$ROOT/scripts/check-badcases.py"

cd "$CORE_PKG"
uv sync --extra dev --extra release

echo "==> Release tests (mock only, parallel)…"
cpus="$(getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 8)"
workers="$cpus"
if [ "$workers" -gt 8 ]; then
  workers=8
fi
uv run pytest \
  -m "not live and not live_chunk and not release_live and not perf" \
  -n "$workers" --dist loadscope --max-worker-restart=0 -q
