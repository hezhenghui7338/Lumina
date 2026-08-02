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
