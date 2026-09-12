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
import urllib.request
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
    assert isinstance(health["uptime_ms"], int)
    assert health["uptime_ms"] >= 0


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


def test_release_smoke_isolates_data_dir():
    """Release sidecar smoke must not open the user's live lumina.db."""
    script = (REPO_ROOT / "scripts" / "build-release.sh").read_text(encoding="utf-8")
    marker = "==> Sidecar startup smoke (embedded binary)"
    start = script.find(marker)
    assert start != -1, "missing sidecar startup smoke step"
    smoke = script[start:]
    assert 'SMOKE_DATA_DIR="$(mktemp -d' in smoke
    assert (
        'LUMINA_DATA_DIR="$SMOKE_DATA_DIR" "$RES/lumina-core" '
        '--host 127.0.0.1 --port "$SMOKE_PORT" &'
    ) in smoke
    assert (
        '\n"$RES/lumina-core" --host 127.0.0.1 --port "$SMOKE_PORT" &'
        not in smoke
    ), "smoke sidecar must set LUMINA_DATA_DIR; bare launch opens the live library"


def test_release_resigns_after_sidecar_embed():
    """Unsigned post-embed bundles make Finder reject 'Set as default' (error 13)."""
    script = (REPO_ROOT / "scripts" / "build-release.sh").read_text(encoding="utf-8")
    marker = "==> Ad-hoc codesign (post-sidecar; Finder default handler)"
    start = script.find(marker)
    assert start != -1, "missing post-sidecar codesign step"
    # Sign after embed smoke, before staging ZIP/DMG.
    smoke_at = script.find("==> Sidecar startup smoke (embedded binary)")
    stage_at = script.find("==> Staging release artifacts")
    assert smoke_at != -1 and stage_at != -1 and smoke_at < start < stage_at
    block = script[start:stage_at]
    assert "codesign --force --deep --options runtime --sign" in block
    assert 'codesign --verify --deep --strict "$APP"' in block
    # ditto to dist must still verify (signature must survive staging).
    staged = script[stage_at : stage_at + 800]
    assert 'codesign --verify --deep --strict "$RELEASE_APP"' in staged


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


def test_e2e_boot_02e_health_during_recover_on_startup(tmp_path, monkeypatch):
    """E2E-BOOT-02e: recover_on_startup must not block /health."""
    from lumina_core.jobs.queue import JobQueue

    monkeypatch.setenv("LUMINA_DATA_DIR", str(tmp_path))
    gate = threading.Event()

    async def blocking_recover(self) -> None:
        while not gate.is_set():
            await asyncio.sleep(0.05)

    monkeypatch.setattr(JobQueue, "recover_on_startup", blocking_recover)
    router = MockModelRouter(responses={})
    app = create_app(Settings(data_dir=tmp_path))
    app.state.lumina.router = router
    app.state.lumina.job_queue.router = router
    set_router(router)

    entered = threading.Event()
    statuses: list[int] = []
    errors: list[BaseException] = []

    def run_client() -> None:
        try:
            with TestClient(app) as client:
                entered.set()
                statuses.append(client.get("/health").status_code)
                gate.set()
        except BaseException as exc:
            errors.append(exc)
            gate.set()

    thread = threading.Thread(target=run_client, daemon=True)
    thread.start()
    if not entered.wait(timeout=3):
        gate.set()
        pytest.fail("lifespan blocked on recover_on_startup; /health never became reachable")
    thread.join(timeout=5)
    assert thread.is_alive() is False
    assert errors == []
    assert statuses == [200]


def test_books_list_responsive_during_startup_catalog_backfill(tmp_path, monkeypatch):
    """Deferred catalog backfill must not starve the first GET /books after /health."""
    from lumina_core.db.repos import BookRepo, SegmentRepo
    from lumina_core.db.schema import init_db

    monkeypatch.setenv("LUMINA_DATA_DIR", str(tmp_path))
    release = threading.Event()
    backfill_started = threading.Event()

    def slow_catalog_backfill(self, *, batch_size: int = 64) -> int:
        backfill_started.set()
        # Parse/work between batches is outside db_lock; list must not wait for it.
        deadline = time.time() + 5
        while not release.is_set() and time.time() < deadline:
            time.sleep(0.05)
        return 0

    monkeypatch.setattr(SegmentRepo, "backfill_catalog_cache", slow_catalog_backfill)
    monkeypatch.setattr(
        SegmentRepo, "backfill_prefix_labels", lambda self, *, batch_size=64: 0
    )

    db_path = tmp_path / "lumina.db"
    conn = init_db(db_path)
    BookRepo(conn).insert(
        id="boot-book",
        title="Boot Book",
        format="txt",
        file_path="/tmp/boot.txt",
        segment_count=0,
        status="unread",
    )
    conn.close()

    router = MockModelRouter(responses={})
    app = create_app(Settings(data_dir=tmp_path))
    app.state.lumina.router = router
    app.state.lumina.job_queue.router = router
    set_router(router)

    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert backfill_started.wait(timeout=3), "deferred catalog backfill never started"
        t0 = time.perf_counter()
        resp = client.get("/books?filter=all&sort=recent")
        elapsed = time.perf_counter() - t0
        release.set()
        assert resp.status_code == 200
        assert elapsed < 1.0, f"GET /books blocked on catalog backfill ({elapsed:.2f}s)"
        books = resp.json()["books"]
        assert any(b["id"] == "boot-book" for b in books)


@pytest.mark.asyncio
async def test_recover_defers_non_read_work_after_fast_path(tmp_path, monkeypatch):
    """TTR: drop trees / catalog / labels run only after recover fast path returns."""
    from lumina_core.db.repos import BookRepo, SegmentRepo
    from lumina_core.db.schema import init_db
    from lumina_core.jobs.queue import JobQueue

    conn = init_db(tmp_path / "order.db")
    BookRepo(conn).insert(
        id="order-book",
        title="Order",
        format="txt",
        file_path="/tmp/order.txt",
        segment_count=1,
        status="unread",
    )
    order: list[str] = []
    real_catalog = SegmentRepo.backfill_catalog_cache
    real_labels = SegmentRepo.backfill_prefix_labels
    real_drop = BookRepo.drop_stored_document_trees

    def tracking_catalog(self, *, batch_size: int = 64) -> int:
        order.append("catalog")
        return real_catalog(self, batch_size=batch_size)

    def tracking_labels(self, *, batch_size: int = 64) -> int:
        order.append("labels")
        return real_labels(self, batch_size=batch_size)

    def tracking_drop(self) -> int:
        order.append("drop_trees")
        return real_drop(self)

    monkeypatch.setattr(SegmentRepo, "backfill_catalog_cache", tracking_catalog)
    monkeypatch.setattr(SegmentRepo, "backfill_prefix_labels", tracking_labels)
    monkeypatch.setattr(BookRepo, "drop_stored_document_trees", tracking_drop)

    q = JobQueue(conn, MockModelRouter(responses={}))
    try:
        await q.recover_on_startup()
        assert order == [], "fast path must not run drop/catalog/labels"
        assert q._worker_count >= 1
        assert q._startup_recovering is False
        task = q._startup_deferred_task or q._catalog_backfill_task
        assert task is not None
        await task
        assert order == ["drop_trees", "catalog", "labels"]
    finally:
        await q.shutdown()
        conn.close()


def test_open_and_segments_responsive_during_slow_drop_trees(tmp_path, monkeypatch):
    """TTR: open + segment window must not wait on deferred drop_stored_document_trees."""
    from lumina_core.db.repos import BookRepo, SegmentRepo
    from lumina_core.db.schema import init_db

    monkeypatch.setenv("LUMINA_DATA_DIR", str(tmp_path))
    release = threading.Event()
    drop_started = threading.Event()

    def slow_drop(self) -> int:
        drop_started.set()
        deadline = time.time() + 5
        while not release.is_set() and time.time() < deadline:
            time.sleep(0.05)
        return 0

    monkeypatch.setattr(BookRepo, "drop_stored_document_trees", slow_drop)
    monkeypatch.setattr(
        SegmentRepo, "backfill_catalog_cache", lambda self, *, batch_size=64: 0
    )
    monkeypatch.setattr(
        SegmentRepo, "backfill_prefix_labels", lambda self, *, batch_size=64: 0
    )

    db_path = tmp_path / "lumina.db"
    conn = init_db(db_path)
    book_id = "ready-book"
    BookRepo(conn).insert(
        id=book_id,
        title="Ready",
        format="txt",
        file_path="/tmp/ready.txt",
        segment_count=1,
        status="reading",
    )
    SegmentRepo(conn).insert_many(
        [
            {
                "id": "seg-0",
                "book_id": book_id,
                "idx": 0,
                "raw_text": "正文第一段",
                "summary_status": "pending",
            }
        ]
    )
    conn.close()

    router = MockModelRouter(responses={})
    app = create_app(Settings(data_dir=tmp_path))
    app.state.lumina.router = router
    app.state.lumina.job_queue.router = router
    set_router(router)

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert drop_started.wait(timeout=3), "deferred drop_trees never started"
        t0 = time.perf_counter()
        opened = client.post(f"/books/{book_id}/open")
        segs = client.get(f"/books/{book_id}/segments", params={"around": 0, "limit": 32})
        elapsed = time.perf_counter() - t0
        release.set()
        assert opened.status_code == 200, opened.text
        assert segs.status_code == 200, segs.text
        assert elapsed < 1.0, f"open/segments blocked on deferred drop ({elapsed:.2f}s)"
        body = segs.json()["segments"]
        assert len(body) >= 1
        assert "raw_text" not in body[0]


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


def test_shutdown_without_server_is_noop(client):
    resp = client.post("/shutdown")
    assert resp.status_code == 200
    assert resp.json()["status"] == "shutting_down"


def test_shutdown_sets_uvicorn_should_exit(client):
    class FakeServer:
        should_exit = False

    fake = FakeServer()
    client.app.state.uvicorn_server = fake
    resp = client.post("/shutdown")
    assert resp.status_code == 200
    assert resp.json()["status"] == "shutting_down"
    assert fake.should_exit is True


def test_cli_attaches_uvicorn_server_for_shutdown():
    main = (CORE_PKG / "lumina_core" / "main.py").read_text(encoding="utf-8")
    assert "app.state.uvicorn_server = server" in main
    routes = (CORE_PKG / "lumina_core" / "api" / "routes.py").read_text(encoding="utf-8")
    assert "server.should_exit = True" in routes


def test_macos_stop_kills_port_listener():
    manager = (REPO_ROOT / "apps/macos/Lumina/Services/SidecarManager.swift").read_text(
        encoding="utf-8"
    )
    assert "userStopped" in manager
    assert "/shutdown" in manager
    assert "SIGKILL" in manager
    assert "func stop(userInitiated: Bool)" in manager
    assert "legacyListenerPID" in manager
    app = (REPO_ROOT / "apps/macos/Lumina/LuminaApp.swift").read_text(encoding="utf-8")
    assert "await sidecar?.stop(userInitiated: false)" in app
    settings = (REPO_ROOT / "apps/macos/Lumina/Features/Settings/SettingsView.swift").read_text(
        encoding="utf-8"
    )
    assert "engineSection" in settings
    assert "sidecar.stop(userInitiated: true)" in settings
    assert "sidecar.restart()" in settings


def test_windows_stop_kills_orphan_pid():
    host = (REPO_ROOT / "apps/windows/Lumina/Services/SidecarHost.cs").read_text(
        encoding="utf-8"
    )
    assert "UserStopped" in host
    assert "ListenerPid" in host
    assert "StopAsync(bool userInitiated" in host
    assert "RestartAsync" in host
    settings = (
        REPO_ROOT / "apps/windows/Lumina/Features/Settings/SettingsPage.xaml"
    ).read_text(encoding="utf-8")
    assert "EngineStopBtn" in settings
    assert "EngineRestartBtn" in settings


def test_post_shutdown_stops_cli_process(tmp_path, monkeypatch):
    """POST /shutdown must end a real uvicorn sidecar, not just return JSON."""
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
        ready = False
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/health", timeout=0.5
                ) as resp:
                    if resp.status == 200:
                        ready = True
                        break
            except OSError:
                time.sleep(0.2)
        if not ready:
            pytest.fail("sidecar did not become healthy on 127.0.0.1")

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/shutdown",
            method="POST",
            data=b"",
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            assert resp.status == 200
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            pytest.fail("sidecar still running after POST /shutdown")
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
