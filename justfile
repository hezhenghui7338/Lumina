# Lumina dev commands

core:
    cd packages/lumina-core && uv run lumina-core

install:
    cd packages/lumina-core && uv python install && uv sync --extra dev

test:
    cd packages/lumina-core && uv run pytest -m "not live and not live_chunk and not release_live and not perf" -q

test-live:
    cd packages/lumina-core && uv run pytest -m live_chunk -q

test-release:
    ./scripts/run-release-tests.sh

test-all:
    cd packages/lumina-core && uv run pytest -q

# Local only: PR/release gates do not run XCTest. Handshake lock is pytest reading Swift source.
test-macos:
    xcodebuild test -project apps/macos/Lumina.xcodeproj -scheme Lumina -destination 'platform=macOS'

release:
    ./scripts/build-release.sh

# Windows release must run on Windows (PowerShell):
#   .\scripts\build-release-windows.ps1
