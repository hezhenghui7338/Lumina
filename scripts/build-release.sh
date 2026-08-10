#!/usr/bin/env bash
# Build a self-contained Lumina.app for end users (embedded lumina-core, no uv/Python required).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${LUMINA_VERSION:-0.8.0}"
DIST="$ROOT/dist"
DERIVED="$ROOT/build/DerivedData"
CORE_PKG="$ROOT/packages/lumina-core"
MACOS="$ROOT/apps/macos"
MAX_SIDECAR_MB=520
MAX_APP_MB=500
MAX_DMG_MB=300

assert_max_dir_mb() {
  local path="$1"
  local max_mb="$2"
  local label="$3"
  local size_mb
  size_mb=$(du -sm "$path" | cut -f1)
  if (( size_mb > max_mb )); then
    echo "ERROR: $label too large: ${size_mb}MB (max ${max_mb}MB): $path" >&2
    exit 1
  fi
}

assert_max_file_mb() {
  local path="$1"
  local max_mb="$2"
  local label="$3"
  local size_mb
  size_mb=$(($(stat -f%z "$path") / 1024 / 1024))
  if (( size_mb > max_mb )); then
    echo "ERROR: $label too large: ${size_mb}MB (max ${max_mb}MB): $path" >&2
    exit 1
  fi
}

echo "==> Lumina release build v${VERSION}"

# --- 0. Release tests (must pass before build) ---
echo "==> Running release tests (must pass)…"
bash "$ROOT/scripts/run-release-tests.sh"

# --- 1. Bundle lumina-core with PyInstaller ---
echo "==> Building lumina-core bundle…"
cd "$CORE_PKG"
# Prefetch default OCR models so collect_all(rapidocr) embeds them (no runtime modelscope download).
uv run python scripts/prefetch_ocr_models.py
uv run pyinstaller lumina-core.spec --noconfirm --clean

SIDECAR_SRC="$CORE_PKG/dist/lumina-core"
if [[ ! -x "$SIDECAR_SRC/lumina-core" ]]; then
  echo "ERROR: PyInstaller output missing: $SIDECAR_SRC/lumina-core" >&2
  exit 1
fi

bash "$ROOT/scripts/prune-sidecar.sh" "$SIDECAR_SRC"
assert_max_dir_mb "$SIDECAR_SRC" "$MAX_SIDECAR_MB" "Pruned sidecar"

echo "==> OCR smoke (embedded sidecar binary)…"
"$SIDECAR_SRC/lumina-core" --smoke-ocr

# --- 2. Build Lumina.app (Release) ---
echo "==> Building Lumina.app (Release)…"
if ! xcodebuild -version >/dev/null 2>&1; then
  echo "ERROR: 需要完整 Xcode（非仅 Command Line Tools）。" >&2
  echo "       macOS 15 请从 Apple 开发者网站下载 Xcode 16.x（勿装 App Store 最新版，可能要求 macOS 26+）。" >&2
  echo "       https://developer.apple.com/download/all/" >&2
  echo "       或使用 GitHub Actions：Actions → Release → Run workflow" >&2
  exit 1
fi
mkdir -p "$DERIVED"
xcodebuild \
  -project "$MACOS/Lumina.xcodeproj" \
  -scheme Lumina \
  -configuration Release \
  -derivedDataPath "$DERIVED" \
  CODE_SIGN_IDENTITY="-" \
  CODE_SIGNING_ALLOWED=NO \
  build

APP="$DERIVED/Build/Products/Release/Lumina.app"
if [[ ! -d "$APP" ]]; then
  echo "ERROR: Xcode build failed — $APP not found" >&2
  exit 1
fi

# --- 3. Embed sidecar into .app bundle ---
echo "==> Embedding lumina-core into app bundle…"
RES="$APP/Contents/Resources/lumina-core"
rm -rf "$RES"
mkdir -p "$RES"
ditto "$SIDECAR_SRC/" "$RES/"
chmod +x "$RES/lumina-core"

echo "==> Sidecar startup smoke (embedded binary)…"
SMOKE_PORT=17433
SMOKE_PID=""
cleanup_smoke() {
  if [[ -n "${SMOKE_PID:-}" ]] && kill -0 "$SMOKE_PID" 2>/dev/null; then
    kill "$SMOKE_PID" 2>/dev/null || true
    wait "$SMOKE_PID" 2>/dev/null || true
  fi
}
trap cleanup_smoke EXIT
"$RES/lumina-core" --host 127.0.0.1 --port "$SMOKE_PORT" &
SMOKE_PID=$!
SMOKE_OK=0
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:${SMOKE_PORT}/health" >/dev/null; then
    SMOKE_OK=1
    break
  fi
  sleep 0.5
done
if [[ "$SMOKE_OK" -ne 1 ]]; then
  echo "ERROR: Embedded sidecar failed /health smoke within 30s" >&2
  exit 1
fi
cleanup_smoke
trap - EXIT

# --- 4. Stage release artifacts ---
echo "==> Staging release artifacts…"
mkdir -p "$DIST"
RELEASE_APP="$DIST/Lumina.app"
rm -rf "$RELEASE_APP"
ditto "$APP" "$RELEASE_APP"

ZIP="$DIST/Lumina-${VERSION}-macOS.zip"
rm -f "$ZIP"
ditto -c -k --sequesterRsrc --keepParent "$RELEASE_APP" "$ZIP"

DMG="$DIST/Lumina-${VERSION}-macOS.dmg"
rm -f "$DMG"
STAGE="$DIST/dmg-stage"
rm -rf "$STAGE"
mkdir -p "$STAGE"
ditto "$RELEASE_APP" "$STAGE/Lumina.app"
ln -s /Applications "$STAGE/Applications"
cat > "$STAGE/开始使用.txt" <<EOF
Lumina ${VERSION} — macOS

1. 将 Lumina.app 拖入 Applications（应用程序）文件夹
2. 打开 Lumina，按引导完成首次设置
3. 首次使用需安装 Ollama（免费本地 AI）：https://ollama.com/download
   安装后在 Ollama 中下载模型 qwen3.5:4b（约 3.4 GB）

无需安装 Python、uv 或 Xcode。
EOF

hdiutil create -volname "Lumina ${VERSION}" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
rm -rf "$STAGE"

assert_max_dir_mb "$RELEASE_APP" "$MAX_APP_MB" "Lumina.app"
assert_max_file_mb "$DMG" "$MAX_DMG_MB" "DMG"

echo ""
echo "✅ Release ready:"
echo "   App:  $RELEASE_APP ($(du -sh "$RELEASE_APP" | cut -f1))"
echo "   ZIP:  $ZIP ($(du -sh "$ZIP" | cut -f1))"
echo "   DMG:  $DMG ($(du -sh "$DMG" | cut -f1))"
echo ""
echo "Upload DMG/ZIP to GitHub Releases for users to download."
