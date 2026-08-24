"""Release mock suite must not hang forever in pytest-xdist teardown."""

from __future__ import annotations

from pathlib import Path

from tests.conftest import xdist_worker_should_force_exit
from tests.support.ocr_helpers import live_ocr_skip_reason

_RELEASE_TESTS = (
    Path(__file__).resolve().parents[4] / "scripts" / "run-release-tests.sh"
)


def test_pytest_timeout_is_configured(pytestconfig):
    timeout = pytestconfig.getoption("timeout")
    if timeout in (None, 0, "0"):
        timeout = pytestconfig.getini("timeout")
    assert float(timeout) > 0, "pytest-timeout must be configured so hung workers self-kill"


def test_xdist_worker_force_exit_after_session():
    env = {"PYTEST_XDIST_WORKER": "gw0"}
    assert not xdist_worker_should_force_exit(env, loaded_modules=set())
    assert xdist_worker_should_force_exit(env, loaded_modules={"onnxruntime"})
    assert xdist_worker_should_force_exit(env, loaded_modules={"rapidocr"})
    assert not xdist_worker_should_force_exit({}, loaded_modules={"onnxruntime"})


def test_release_script_caps_xdist_and_disables_restarts():
    script = _RELEASE_TESTS.read_text(encoding="utf-8")
    assert "--max-worker-restart=0" in script
    assert "workers=8" in script
    assert '-n "$workers"' in script


def test_live_ocr_skip_does_not_init_engine_under_xdist(monkeypatch):
    def boom():
        raise AssertionError("must not construct RapidOCR/ORT during skip check")

    monkeypatch.setattr("lumina_core.ingest.ocr._ensure_engine", boom)
    reason = live_ocr_skip_reason({"PYTEST_XDIST_WORKER": "gw3"})
    assert reason is not None
    assert "xdist" in reason


def test_live_ocr_skip_uses_import_not_engine(monkeypatch):
    def boom():
        raise AssertionError("must not construct RapidOCR/ORT during skip check")

    monkeypatch.setattr("lumina_core.ingest.ocr._ensure_engine", boom)
    live_ocr_skip_reason({})
