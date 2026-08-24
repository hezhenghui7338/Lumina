"""Release bundle checks for OCR / OpenCV dylibs."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
PRUNE_SCRIPT = ROOT / "scripts" / "prune-sidecar.sh"


@pytest.mark.skipif(sys.platform != "darwin", reason="prune-sidecar OpenCV layout is macOS-specific")
def test_prune_sidecar_preserves_opencv_dylibs(tmp_path: Path):
    """prune-sidecar must not delete cv2 dylibs (breaks OCR in release builds)."""
    sidecar = tmp_path / "lumina-core"
    internal = sidecar / "_internal"
    dylibs = internal / "cv2" / ".dylibs"
    dylibs.mkdir(parents=True)
    libavif = dylibs / "libavif.16.3.0.dylib"
    libavif.write_bytes(b"fake-dylib")
    (internal / "libavif.16.3.0.dylib").symlink_to("cv2/.dylibs/libavif.16.3.0.dylib")
    (internal / "rapidocr" / "models").mkdir(parents=True)

    subprocess.run(
        ["bash", str(PRUNE_SCRIPT), str(sidecar)],
        check=True,
        cwd=ROOT,
    )

    assert libavif.is_file(), "libavif dylib must survive prune-sidecar"
    assert (internal / "libavif.16.3.0.dylib").exists(), "symlink target must remain valid"


@pytest.mark.skipif(sys.platform == "win32", reason="uses prune-sidecar.sh")
def test_prune_sidecar_strips_onnxruntime_ballast(tmp_path: Path):
    """Conversion/test extras must leave; capi must remain for RapidOCR inference."""
    sidecar = tmp_path / "lumina-core"
    internal = sidecar / "_internal"
    ort = internal / "onnxruntime"
    (ort / "capi").mkdir(parents=True)
    (ort / "capi" / "onnxruntime_inference_collection.py").write_text("ok\n")
    for name in ("transformers", "quantization", "tools", "datasets"):
        ballast = ort / name
        ballast.mkdir()
        (ballast / "deadweight.py").write_text("unused\n")
    (internal / "rapidocr" / "models").mkdir(parents=True)

    subprocess.run(
        ["bash", str(PRUNE_SCRIPT), str(sidecar)],
        check=True,
        cwd=ROOT,
    )

    assert (ort / "capi" / "onnxruntime_inference_collection.py").is_file()
    for name in ("transformers", "quantization", "tools", "datasets"):
        assert not (ort / name).exists(), f"onnxruntime/{name} must be pruned"


def test_release_scripts_pin_cpython_from_python_version():
    """GitHub runners default to CPython 3.14; that sidecar made Lumina.app 501MB."""
    pin = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    assert pin == "3.11"
    sh = (ROOT / "scripts" / "build-release.sh").read_text(encoding="utf-8")
    tests = (ROOT / "scripts" / "run-release-tests.sh").read_text(encoding="utf-8")
    ps1 = (ROOT / "scripts" / "build-release-windows.ps1").read_text(encoding="utf-8")
    mac_wf = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    win_wf = (ROOT / ".github" / "workflows" / "release-windows.yml").read_text(
        encoding="utf-8"
    )
    for body in (sh, tests, ps1):
        assert "UV_PYTHON" in body
        assert ".python-version" in body
    assert 'python-version: "3.11"' in mac_wf
    assert 'python-version: "3.11"' in win_wf


def test_windows_probe_overrides_switch_has_semicolon():
    """CS1002: expression-bodied switch must end with }; or Release Windows fails."""
    import re

    text = (
        ROOT
        / "apps"
        / "windows"
        / "Lumina"
        / "Features"
        / "Settings"
        / "SettingsPage.xaml.cs"
    ).read_text(encoding="utf-8")
    assert re.search(
        r"ProbeOverrides\([^)]*\) => resourceId switch\s*\{.*?\n    \};",
        text,
        re.S,
    )
