"""Release identity copies must be written from pyproject + CHUNKER_VERSION."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from lumina_core.config import CHUNKER_VERSION, CORE_VERSION

REPO_ROOT = Path(__file__).resolve().parents[4]
_SYNC_PATH = REPO_ROOT / "scripts" / "sync-release-identity.py"


def _sync_mod():
    spec = importlib.util.spec_from_file_location("sync_release_identity", _SYNC_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_sync_script_is_idempotent_on_this_repo():
    mod = _sync_mod()
    first = mod.sync_identity(REPO_ROOT)
    second = mod.sync_identity(REPO_ROOT)
    assert first["version"] == CORE_VERSION
    assert first["chunker_version"] == CHUNKER_VERSION
    assert second["changed"] == "none"


def test_sync_rewrites_stale_copies(tmp_path):
    mod = _sync_mod()
    root = tmp_path
    pyproject = root / "packages" / "lumina-core" / "pyproject.toml"
    config = root / "packages" / "lumina-core" / "lumina_core" / "config.py"
    init = root / "packages" / "lumina-core" / "lumina_core" / "__init__.py"
    pbx = root / "apps" / "macos" / "Lumina.xcodeproj" / "project.pbxproj"
    csproj = root / "apps" / "windows" / "Lumina" / "Lumina.csproj"
    swift = root / "apps" / "macos" / "Lumina" / "Services" / "SidecarReadiness.swift"
    csharp = root / "apps" / "windows" / "Lumina" / "Services" / "SidecarReadiness.cs"
    for path in (pyproject, config, init, pbx, csproj, swift, csharp):
        path.parent.mkdir(parents=True, exist_ok=True)

    pyproject.write_text('version = "0.1.0"\n', encoding="utf-8")
    config.write_text(
        'CORE_VERSION = "0.0.0"\nCHUNKER_VERSION = "3"\n', encoding="utf-8"
    )
    init.write_text('__version__ = "0.0.0"\n', encoding="utf-8")
    pbx.write_text(
        "MARKETING_VERSION = 0.0.0;\nCURRENT_PROJECT_VERSION = 1;\n",
        encoding="utf-8",
    )
    csproj.write_text("<Version>0.0.0</Version>\n", encoding="utf-8")
    swift.write_text(
        'static let expectedChunkerVersion = "1"\n', encoding="utf-8"
    )
    csharp.write_text(
        'public const string ExpectedChunkerVersion = "1";\n', encoding="utf-8"
    )

    result = mod.sync_identity(root, version="9.9.9")
    assert result["version"] == "9.9.9"
    assert result["chunker_version"] == "3"
    assert 'version = "9.9.9"' in pyproject.read_text(encoding="utf-8")
    assert 'CORE_VERSION = "9.9.9"' in config.read_text(encoding="utf-8")
    assert 'CHUNKER_VERSION = "3"' in config.read_text(encoding="utf-8")
    assert '__version__ = "9.9.9"' in init.read_text(encoding="utf-8")
    assert "MARKETING_VERSION = 9.9.9;" in pbx.read_text(encoding="utf-8")
    assert "CURRENT_PROJECT_VERSION = 9.9.9;" in pbx.read_text(encoding="utf-8")
    assert "<Version>9.9.9</Version>" in csproj.read_text(encoding="utf-8")
    assert 'expectedChunkerVersion = "3"' in swift.read_text(encoding="utf-8")
    assert 'ExpectedChunkerVersion = "3"' in csharp.read_text(encoding="utf-8")


def test_release_scripts_sync_identity_before_packaging():
    sh = (REPO_ROOT / "scripts" / "build-release.sh").read_text(encoding="utf-8")
    ps1 = (REPO_ROOT / "scripts" / "build-release-windows.ps1").read_text(
        encoding="utf-8"
    )
    assert "sync-release-identity.py" in sh
    assert "sync-release-identity.py" in ps1
    assert sh.find("sync-release-identity.py") < sh.find("pyinstaller")
    assert sh.find("sync-release-identity.py") < sh.find("xcodebuild")
    assert "MARKETING_VERSION=\"$VERSION\"" in sh
    assert "CURRENT_PROJECT_VERSION=\"$VERSION\"" in sh
    assert ps1.lower().find("sync-release-identity.py") < ps1.lower().find(
        "pyinstaller"
    )
    assert "-p:Version=$Version" in ps1
