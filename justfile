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
# LuminaTests runs inside the app, and LaunchServices refuses to launch a second
# instance of the same bundle id. So a running Lumina (or a parallel clone of the
# test host) turns into an opaque "Could not launch LuminaTests".
test-macos:
    @if pgrep -x Lumina >/dev/null 2>&1; then echo "先退出正在运行的 Lumina：xcodebuild 无法再启动同一个 App 作为测试宿主"; exit 1; fi
    xcodebuild test -project apps/macos/Lumina.xcodeproj -scheme Lumina -destination 'platform=macOS' -parallel-testing-enabled NO

release:
    ./scripts/build-release.sh

# Windows release must run on Windows (PowerShell):
#   .\scripts\build-release-windows.ps1
