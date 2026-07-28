# Lumina dev commands

core:
    cd packages/lumina-core && uv run lumina-core

install:
    cd packages/lumina-core && uv sync --extra dev

test:
    cd packages/lumina-core && uv run pytest -m "not live and not live_chunk and not perf" -q

test-live:
    cd packages/lumina-core && uv run pytest -m live_chunk -q

test-all:
    cd packages/lumina-core && uv run pytest -q

release:
    ./scripts/build-release.sh
