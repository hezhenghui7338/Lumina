#!/usr/bin/env python3
"""Write every release-identity copy from pyproject + CHUNKER_VERSION.

Called by macOS/Windows release builds so app version, sidecar core_version,
desktop marketing versions, and chunker handshake constants cannot drift.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_VERSION_RE = re.compile(r"^version\s*=\s*\"([^\"]+)\"", re.M)
_CORE_RE = re.compile(r'^CORE_VERSION\s*=\s*"[^"]+"', re.M)
_PY_DUNDER_RE = re.compile(r'^__version__\s*=\s*"[^"]+"', re.M)
_CHUNKER_RE = re.compile(r'^CHUNKER_VERSION\s*=\s*"([^"]+)"', re.M)
_MARKETING_RE = re.compile(r"MARKETING_VERSION = [^;]+;")
_CURRENT_RE = re.compile(r"CURRENT_PROJECT_VERSION = [^;]+;")
_CSPROJ_RE = re.compile(r"<Version>[^<]+</Version>")
_SWIFT_CHUNKER_RE = re.compile(
    r'static let expectedChunkerVersion = "[^"]+"'
)
_CS_CHUNKER_RE = re.compile(
    r'public const string ExpectedChunkerVersion = "[^"]+";'
)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def pyproject_path(root: Path) -> Path:
    return root / "packages" / "lumina-core" / "pyproject.toml"


def config_path(root: Path) -> Path:
    return root / "packages" / "lumina-core" / "lumina_core" / "config.py"


def read_pyproject_version(root: Path) -> str:
    text = pyproject_path(root).read_text(encoding="utf-8")
    match = _VERSION_RE.search(text)
    if not match:
        raise ValueError(f"project version not found in {pyproject_path(root)}")
    return match.group(1)


def read_chunker_version(root: Path) -> str:
    text = config_path(root).read_text(encoding="utf-8")
    match = _CHUNKER_RE.search(text)
    if not match:
        raise ValueError(f"CHUNKER_VERSION not found in {config_path(root)}")
    return match.group(1)


def _replace(path: Path, pattern: re.Pattern[str], replacement: str) -> bool:
    text = path.read_text(encoding="utf-8")
    new, count = pattern.subn(replacement, text)
    if count == 0:
        raise ValueError(f"{path}: pattern not found: {pattern.pattern}")
    if new == text:
        return False
    path.write_text(new, encoding="utf-8")
    return True


def write_pyproject_version(root: Path, version: str) -> bool:
    return _replace(pyproject_path(root), _VERSION_RE, f'version = "{version}"')


def sync_identity(root: Path, version: str | None = None) -> dict[str, str]:
    """Align copies to `version` (default: pyproject). Return the resolved identity."""
    if version:
        write_pyproject_version(root, version)
    resolved = read_pyproject_version(root)
    chunker = read_chunker_version(root)

    changed = []
    if _replace(
        config_path(root),
        _CORE_RE,
        f'CORE_VERSION = "{resolved}"',
    ):
        changed.append("CORE_VERSION")
    if _replace(
        root / "packages" / "lumina-core" / "lumina_core" / "__init__.py",
        _PY_DUNDER_RE,
        f'__version__ = "{resolved}"',
    ):
        changed.append("__version__")
    if _replace(
        root / "apps" / "macos" / "Lumina.xcodeproj" / "project.pbxproj",
        _MARKETING_RE,
        f"MARKETING_VERSION = {resolved};",
    ):
        changed.append("MARKETING_VERSION")
    if _replace(
        root / "apps" / "macos" / "Lumina.xcodeproj" / "project.pbxproj",
        _CURRENT_RE,
        f"CURRENT_PROJECT_VERSION = {resolved};",
    ):
        changed.append("CURRENT_PROJECT_VERSION")
    if _replace(
        root / "apps" / "windows" / "Lumina" / "Lumina.csproj",
        _CSPROJ_RE,
        f"<Version>{resolved}</Version>",
    ):
        changed.append("csproj Version")
    if _replace(
        root / "apps" / "macos" / "Lumina" / "Services" / "SidecarReadiness.swift",
        _SWIFT_CHUNKER_RE,
        f'static let expectedChunkerVersion = "{chunker}"',
    ):
        changed.append("expectedChunkerVersion")
    if _replace(
        root / "apps" / "windows" / "Lumina" / "Services" / "SidecarReadiness.cs",
        _CS_CHUNKER_RE,
        f'public const string ExpectedChunkerVersion = "{chunker}";',
    ):
        changed.append("ExpectedChunkerVersion")

    return {
        "version": resolved,
        "chunker_version": chunker,
        "changed": ",".join(changed) if changed else "none",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version",
        help="Write this version into pyproject.toml then sync copies. Default: keep pyproject.",
    )
    parser.add_argument(
        "--print-version",
        action="store_true",
        help="Print pyproject version and exit (no writes).",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=repo_root(),
        help="Repository root",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        if args.print_version:
            print(read_pyproject_version(root), end="")
            return 0
        result = sync_identity(root, version=args.version)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        f"release identity version={result['version']} "
        f"chunker_version={result['chunker_version']} "
        f"updated={result['changed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
