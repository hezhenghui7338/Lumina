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
    # rapidocr import alone does not load ORT Eigen pools — must not force-exit.
    assert not xdist_worker_should_force_exit(env, loaded_modules={"rapidocr"})
    assert not xdist_worker_should_force_exit({}, loaded_modules={"onnxruntime"})


def test_release_script_caps_xdist_and_disables_restarts():
    script = _RELEASE_TESTS.read_text(encoding="utf-8")
    assert "--max-worker-restart=0" in script
    assert "workers=8" in script
    assert '-n "$workers"' in script


def test_agent_log_is_noop():
    """Sync debug append under xdist blocked the event loop (~600MB shared log)."""
    import inspect

    from lumina_core.debug_agent_log import agent_log

    source = inspect.getsource(agent_log)
    assert "open(" not in source
    assert agent_log(hypothesis_id="t", location="t", message="t") is None


def test_live_ocr_skip_does_not_init_engine_under_xdist(monkeypatch):
    def boom():
        raise AssertionError("must not construct RapidOCR/ORT during skip check")

    monkeypatch.setattr("lumina_core.ingest.ocr._ensure_engine", boom)
    reason = live_ocr_skip_reason({"PYTEST_XDIST_WORKER": "gw3"})
    assert reason is not None
    assert "xdist" in reason


def test_live_ocr_skip_uses_import_not_engine(monkeypatch):
    """Non-xdist path may import fitz/rapidocr; never construct the ORT engine.

    Under xdist, inject stub modules so we do not leave real `rapidocr` in
    sys.modules (and never touch onnxruntime).
    """
    import sys
    import types

    def boom():
        raise AssertionError("must not construct RapidOCR/ORT during skip check")

    monkeypatch.setattr("lumina_core.ingest.ocr._ensure_engine", boom)
    monkeypatch.setitem(sys.modules, "fitz", types.ModuleType("fitz"))
    monkeypatch.setitem(sys.modules, "rapidocr", types.ModuleType("rapidocr"))
    assert live_ocr_skip_reason({}) is None
