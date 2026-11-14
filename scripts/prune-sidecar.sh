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

# trafilatura pulls babel; keep zh + a few en locales for RSS/news extraction.
if [[ -d "$INTERNAL/babel/locale-data" ]]; then
  find "$INTERNAL/babel/locale-data" -name "*.dat" \
    ! -name "zh*" \
    ! -name "en.dat" \
    ! -name "en_001.dat" \
    ! -name "en_US.dat" \
    ! -name "en_GB.dat" \
    -delete
fi

# jusText ships ~100 language stoplists (~2MB). URL import only needs common langs;
# trafilatura only requires the stoplists directory to exist (os.listdir).
JUSTEXT_STOP="$INTERNAL/justext/stoplists"
if [[ -d "$JUSTEXT_STOP" ]]; then
  find "$JUSTEXT_STOP" -type f -name "*.txt" \
    ! -name "English.txt" \
    ! -name "Simple_English.txt" \
    ! -name "French.txt" \
    ! -name "German.txt" \
    ! -name "Spanish.txt" \
    ! -name "Portuguese.txt" \
    ! -name "Italian.txt" \
    ! -name "Russian.txt" \
    ! -name "Korean.txt" \
    ! -name "Indonesian.txt" \
    ! -name "Vietnamese.txt" \
    ! -name "Arabic.txt" \
    ! -name "Hindi.txt" \
    ! -name "Dutch.txt" \
    ! -name "Polish.txt" \
    ! -name "Turkish.txt" \
    ! -name "Swedish.txt" \
    ! -name "Ukrainian.txt" \
    -delete
fi

# ddgs → fake_useragent ships a ~2.5MB browsers.jsonl; keep the top usage rows.
UA_JSONL="$INTERNAL/fake_useragent/data/browsers.jsonl"
if [[ -f "$UA_JSONL" ]]; then
  python3 - "$UA_JSONL" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
rows.sort(key=lambda row: float(row.get("percent") or 0), reverse=True)
kept = rows[:200]
path.write_text(
    "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in kept),
    encoding="utf-8",
)
PY
fi

# RapidOCR only needs onnxruntime capi at inference time. collect_all(onnxruntime)
# also ships conversion/test ballast (~4MB) that pushed Lumina.app over 500MB.
ORT="$INTERNAL/onnxruntime"
if [[ -d "$ORT" ]]; then
  rm -rf "$ORT/transformers" "$ORT/quantization" "$ORT/tools" "$ORT/datasets"
fi

# OpenCV (cv2) dylibs must stay intact — cv2.abi3.so links libavif/libav* at runtime.
# Do NOT prune cv2/.dylibs; PyInstaller symlinks under _internal/ break if targets are removed.

if [[ -d "$INTERNAL/cv2/.dylibs" ]]; then
  if ! compgen -G "$INTERNAL/cv2/.dylibs/libavif"*.dylib > /dev/null; then
    echo "ERROR: OpenCV libavif dylib missing under $INTERNAL/cv2/.dylibs" >&2
    exit 1
  fi
fi

broken_links="$(find "$INTERNAL" -maxdepth 1 -type l ! -exec test -e {} \; -print 2>/dev/null || true)"
if [[ -n "$broken_links" ]]; then
  echo "ERROR: broken symlinks in sidecar _internal (OpenCV deps?):" >&2
  echo "$broken_links" >&2
  exit 1
fi

# Guard against accidental packaging of cursor-sdk into the release sidecar
# (~large Node/runtime footprint). Cursor SDK is downloaded on demand into the
# user data directory (Application Support), never into _internal/.
if [[ -d "$INTERNAL/cursor_sdk" ]]; then
  echo "ERROR: cursor_sdk must not be in release sidecar: $INTERNAL/cursor_sdk" >&2
  echo "Install Cursor SDK from Settings into the user data directory instead." >&2
  exit 1
fi

if compgen -G "$INTERNAL/rapidocr/models/"'*_small.onnx' > /dev/null; then
  echo "ERROR: small OCR models must be pruned from release sidecar" >&2
  exit 1
fi

if [[ -d "$ORT" ]]; then
  for ballast in transformers quantization tools datasets; do
    if [[ -e "$ORT/$ballast" ]]; then
      echo "ERROR: onnxruntime $ballast must be pruned from release sidecar" >&2
      exit 1
    fi
  done
  if [[ ! -d "$ORT/capi" ]]; then
    echo "ERROR: onnxruntime capi missing after prune: $ORT/capi" >&2
    exit 1
  fi
fi

if [[ -d "$JUSTEXT_STOP" ]]; then
  if [[ ! -f "$JUSTEXT_STOP/English.txt" ]]; then
    echo "ERROR: justext English stoplist missing after prune" >&2
    exit 1
  fi
  leftover="$(find "$JUSTEXT_STOP" -type f -name "*.txt" ! -name "English.txt" ! -name "Simple_English.txt" ! -name "French.txt" ! -name "German.txt" ! -name "Spanish.txt" ! -name "Portuguese.txt" ! -name "Italian.txt" ! -name "Russian.txt" ! -name "Korean.txt" ! -name "Indonesian.txt" ! -name "Vietnamese.txt" ! -name "Arabic.txt" ! -name "Hindi.txt" ! -name "Dutch.txt" ! -name "Polish.txt" ! -name "Turkish.txt" ! -name "Swedish.txt" ! -name "Ukrainian.txt" -print | head -n 1 || true)"
  if [[ -n "$leftover" ]]; then
    echo "ERROR: unexpected justext stoplist remained after prune: $leftover" >&2
    exit 1
  fi
fi

if [[ -f "$UA_JSONL" ]]; then
  ua_lines="$(wc -l < "$UA_JSONL" | tr -d '[:space:]')"
  if [[ "$ua_lines" -gt 200 ]]; then
    echo "ERROR: fake_useragent browsers.jsonl still has $ua_lines lines (max 200)" >&2
    exit 1
  fi
fi

echo "==> Sidecar pruned ($(du -sh "$SIDECAR" | cut -f1))"
