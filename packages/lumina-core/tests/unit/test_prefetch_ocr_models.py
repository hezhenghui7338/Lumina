"""Release prefetch must download OCR weights when RapidOCR is lazy."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "prefetch_ocr_models.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("prefetch_ocr_models", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_warm_models_loads_lazy_rapidocr_sessions():
    module = _load()
    loaded: list[str] = []

    class _Engine:
        def _load_det_model(self):
            loaded.append("det")

        def _load_cls_model(self):
            loaded.append("cls")

        def _load_rec_model(self):
            loaded.append("rec")

    module.warm_models(_Engine())
    assert loaded == ["det", "cls", "rec"]
