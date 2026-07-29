#!/usr/bin/env python3
"""Prefetch RapidOCR PP-OCRv6 medium models into site-packages before PyInstaller.

Must match production defaults in lumina_core.ingest.ocr._ensure_engine
(LUMINA_OCR_TIER=medium, LUMINA_OCR_LANG=ch).
"""

from __future__ import annotations

import sys
from pathlib import Path

REQUIRED = (
    "PP-OCRv6_det_medium.onnx",
    "PP-OCRv6_rec_medium.onnx",
    "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
)


def _models_dir() -> Path:
    import rapidocr

    return Path(rapidocr.__file__).resolve().parent / "models"


def main() -> int:
    from rapidocr import ModelType, OCRVersion, RapidOCR

    print("==> Prefetching RapidOCR PP-OCRv6 medium (ch)…")
    RapidOCR(
        params={
            "Det.model_type": ModelType.MEDIUM,
            "Det.ocr_version": OCRVersion.PPOCRV6,
            "Det.lang_type": "ch",
            "Rec.model_type": ModelType.MEDIUM,
            "Rec.ocr_version": OCRVersion.PPOCRV6,
            "Rec.lang_type": "ch",
        }
    )

    models = _models_dir()
    missing = [name for name in REQUIRED if not (models / name).is_file()]
    if missing:
        print(f"ERROR: OCR models missing under {models}:", file=sys.stderr)
        for name in missing:
            print(f"  - {name}", file=sys.stderr)
        return 1

    print(f"==> OCR models ready in {models}")
    for name in REQUIRED:
        path = models / name
        print(f"    {name} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
