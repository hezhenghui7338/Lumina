"""E2E-BOOT-02 / E2E-PRIV-01: Sidecar startup health and localhost bind."""

from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumina_core.config import Settings
from lumina_core.main import create_app
from lumina_core.models.router import set_router
from tests.support.mock_router import MockModelRouter

CORE_PKG = Path(__file__).resolve().parents[2]


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
    assert resp.json() == {"status": "ok"}


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
