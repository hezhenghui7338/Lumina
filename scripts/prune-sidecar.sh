#!/usr/bin/env bash
# Remove redundant files from PyInstaller sidecar before embedding into Lumina.app.
set -euo pipefail

SIDECAR="${1:?usage: prune-sidecar.sh <path-to-lumina-core-bundle>}"
INTERNAL="$SIDECAR/_internal"

if [[ ! -d "$INTERNAL" ]]; then
  echo "ERROR: sidecar _internal missing: $INTERNAL" >&2
  exit 1
fi

echo "==> Pruning sidecar bundle…"

# Default release uses medium OCR tier only; small models are unused ballast.
if [[ -d "$INTERNAL/rapidocr/models" ]]; then
  rm -f "$INTERNAL/rapidocr/models/"*_small.onnx
fi

# trafilatura pulls babel; keep zh/en locale data for RSS/news extraction.
if [[ -d "$INTERNAL/babel/locale-data" ]]; then
  find "$INTERNAL/babel/locale-data" -name "*.dat" \
    ! -name "zh*" ! -name "en*" -delete
fi

# opencv-python-headless should omit FFmpeg; strip leftovers if present.
if [[ -d "$INTERNAL/cv2/.dylibs" ]]; then
  rm -f "$INTERNAL/cv2/.dylibs"/libav*.dylib
  rm -f "$INTERNAL/cv2/.dylibs"/libsw*.dylib
fi

# Guard against legacy cursor-sdk artifacts (~150 MB Node runtime) in release bundles.
if [[ -d "$INTERNAL/cursor_sdk" ]]; then
  echo "ERROR: cursor_sdk must not be in release sidecar: $INTERNAL/cursor_sdk" >&2
  exit 1
fi

if compgen -G "$INTERNAL/rapidocr/models/"'*_small.onnx' > /dev/null; then
  echo "ERROR: small OCR models must be pruned from release sidecar" >&2
  exit 1
fi

echo "==> Sidecar pruned ($(du -sh "$SIDECAR" | cut -f1))"
