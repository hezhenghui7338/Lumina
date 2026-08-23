"""E2E-BOOT-02 / E2E-PRIV-01: Sidecar startup health and localhost bind."""

from __future__ import annotations

import asyncio
import importlib.util
import re
import socket
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumina_core.config import CHUNKER_VERSION, CORE_VERSION, Settings
from lumina_core.main import create_app
from lumina_core.models.router import set_router
from tests.support.mock_router import MockModelRouter

CORE_PKG = Path(__file__).resolve().parents[2]
REPO_ROOT = Path(__file__).resolve().parents[4]
_ASSERT_HEALTH_PATH = REPO_ROOT / "scripts" / "assert-health-chunker-version.py"


def _assert_health_mod():
    spec = importlib.util.spec_from_file_location(
        "assert_health_chunker_version", _ASSERT_HEALTH_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMINA_DATA_DIR", str(tmp_path))
    router = MockModelRouter(responses={})
    app = create_app(Settings(data_dir=tmp_path))
    app.state.lumina.router = router
    app.state.lumina.job_queue.router = router
    set_router(router)
    with TestClient(app) as c:
        yield c


def test_e2e_boot_02d_health_responds_immediately(client):
    """E2E-BOOT-02d: GET /health returns ok as soon as app is up."""
    resp = client.get("/health")
    assert resp.status_code == 200
    health = resp.json()
    assert health["status"] == "ok"
    assert health["pid"] > 1
    assert health["chunker_version"] == CHUNKER_VERSION
    assert health["core_version"] == CORE_VERSION
    assert isinstance(health["started_at"], int)
    assert health["started_at"] > 1
    assert isinstance(health["executable"], str)
    assert health["executable"]


def test_macos_sidecar_expected_chunker_version_matches_core():
    """macOS must handshake the same CHUNKER_VERSION or library/news/settings never load."""
    swift = (REPO_ROOT / "apps/macos/Lumina/Services/SidecarReadiness.swift").read_text(
        encoding="utf-8"
    )
    needle = f'static let expectedChunkerVersion = "{CHUNKER_VERSION}"'
    assert needle in swift, (
        "SidecarReadiness.expectedChunkerVersion must equal "
        f"lumina-core CHUNKER_VERSION={CHUNKER_VERSION!r}"
    )


def test_windows_sidecar_expected_chunker_version_matches_core():
    csharp = (REPO_ROOT / "apps/windows/Lumina/Services/SidecarReadiness.cs").read_text(
        encoding="utf-8"
    )
    needle = f'public const string ExpectedChunkerVersion = "{CHUNKER_VERSION}"'
    assert needle in csharp, (
        "SidecarReadiness.ExpectedChunkerVersion must equal "
        f"lumina-core CHUNKER_VERSION={CHUNKER_VERSION!r}"
    )


def test_core_version_matches_shipped_apps():
    """Engine identity must move with the desktop app version, not only CHUNKER_VERSION."""
    pyproject = tomllib.loads(
        (REPO_ROOT / "packages/lumina-core/pyproject.toml").read_text(encoding="utf-8")
    )
    assert pyproject["project"]["version"] == CORE_VERSION
    pbx = (REPO_ROOT / "apps/macos/Lumina.xcodeproj/project.pbxproj").read_text(
        encoding="utf-8"
    )
    marketing = set(re.findall(r"MARKETING_VERSION = ([^;]+);", pbx))
    assert marketing == {CORE_VERSION}
    csproj = (REPO_ROOT / "apps/windows/Lumina/Lumina.csproj").read_text(encoding="utf-8")
    assert f"<Version>{CORE_VERSION}</Version>" in csproj


def test_macos_sidecar_replaces_orphan_on_core_version_mismatch():
    swift = (REPO_ROOT / "apps/macos/Lumina/Services/SidecarReadiness.swift").read_text(
        encoding="utf-8"
    )
    assert "shouldReplaceOrphan" in swift
    assert "coreVersion" in swift
    manager = (REPO_ROOT / "apps/macos/Lumina/Services/SidecarManager.swift").read_text(
        encoding="utf-8"
    )
    assert "shouldReplaceOrphan" in manager
    assert "expectedCoreVersion" in manager


def test_release_smoke_asserts_health_chunker_version():
    """build-release.sh must compare /health JSON to CHUNKER_VERSION, not HTTP 200 only."""
    script = (REPO_ROOT / "scripts" / "build-release.sh").read_text(encoding="utf-8")
    assert "assert-health-chunker-version.py" in script
    assert 'curl -sf "http://127.0.0.1:${SMOKE_PORT}/health" >/dev/null' not in script

    helper = _assert_health_mod()
    expected = helper.read_chunker_version(
        REPO_ROOT / "packages" / "lumina-core" / "lumina_core" / "config.py"
    )
    assert expected == CHUNKER_VERSION
    assert helper.check_health_chunker_version(
        {"status": "ok", "chunker_version": expected}, expected
    ) == expected
    core = helper.read_core_version(
        REPO_ROOT / "packages" / "lumina-core" / "lumina_core" / "config.py"
    )
    assert core == CORE_VERSION
    assert helper.check_health_core_version(
        {"status": "ok", "core_version": core}, core
    ) == core
    try:
        helper.check_health_chunker_version(
            {"status": "ok", "chunker_version": "7"}, expected
        )
    except ValueError as exc:
        assert "chunker_version" in str(exc)
    else:
        raise AssertionError("stale chunker_version must fail release smoke")
    try:
        helper.check_health_core_version(
            {"status": "ok", "core_version": "0.0.1"}, core
        )
    except ValueError as exc:
        assert "core_version" in str(exc)
    else:
        raise AssertionError("stale core_version must fail release smoke")


def test_e2e_boot_02e_health_during_recover_on_startup(client):
    """E2E-BOOT-02e: recover_on_startup must not block /health."""
    state = client.app.state.lumina
    health_during: list[int] = []

    async def slow_recover() -> None:
        await asyncio.sleep(0.3)
        await state.job_queue.recover_on_startup()

    def worker() -> None:
        asyncio.run(slow_recover())

    thread = threading.Thread(target=worker)
    thread.start()
    time.sleep(0.05)
    health_during.append(client.get("/health").status_code)
    thread.join(timeout=10)
    assert thread.is_alive() is False
    assert health_during == [200]


def test_e2e_priv_01_settings_default_localhost():
    """E2E-PRIV-01: Sidecar defaults to localhost bind."""
    settings = Settings()
    assert settings.host == "127.0.0.1"
    assert settings.port == 17432


@pytest.mark.skipif(sys.platform != "darwin", reason="subprocess bind check is macOS CI/local only")
def test_e2e_priv_01_cli_binds_localhost_only(tmp_path, monkeypatch):
    """E2E-PRIV-01: lumina-core CLI listens on 127.0.0.1 only."""
    monkeypatch.setenv("LUMINA_DATA_DIR", str(tmp_path))
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "lumina_core.main", "--host", "127.0.0.1", "--port", str(port)],
        cwd=CORE_PKG,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.2)
        else:
            pytest.fail("sidecar did not start listening on 127.0.0.1")

        lsof = subprocess.run(
            ["/usr/sbin/lsof", "-iTCP:%d" % port, "-sTCP:LISTEN", "-nP"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert lsof.returncode == 0, lsof.stderr
        assert f"127.0.0.1:{port}" in lsof.stdout
        assert f"*:{port}" not in lsof.stdout
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
