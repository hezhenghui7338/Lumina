#!/usr/bin/env bash
# Build a self-contained Lumina.app for end users (embedded lumina-core, no uv/Python required).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${LUMINA_VERSION:-0.1.0}"
DIST="$ROOT/dist"
DERIVED="$ROOT/build/DerivedData"
CORE_PKG="$ROOT/packages/lumina-core"
MACOS="$ROOT/apps/macos"

echo "==> Lumina release build v${VERSION}"

# --- 1. Bundle lumina-core with PyInstaller ---
echo "==> Building lumina-core bundle…"
cd "$CORE_PKG"
uv sync --extra release
uv run pyinstaller lumina-core.spec --noconfirm --clean

SIDECAR_SRC="$CORE_PKG/dist/lumina-core"
if [[ ! -x "$SIDECAR_SRC/lumina-core" ]]; then
  echo "ERROR: PyInstaller output missing: $SIDECAR_SRC/lumina-core" >&2
  exit 1
fi

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

echo ""
echo "✅ Release ready:"
echo "   App:  $RELEASE_APP"
echo "   ZIP:  $ZIP"
echo "   DMG:  $DMG"
echo ""
echo "Upload DMG/ZIP to GitHub Releases for users to download."
