"""Release mock suite must not hang forever in pytest-xdist teardown."""

from __future__ import annotations

from tests.conftest import xdist_worker_should_force_exit
from tests.support.ocr_helpers import live_ocr_skip_reason


def test_pytest_timeout_is_configured(pytestconfig):
    timeout = pytestconfig.getoption("timeout")
    if timeout in (None, 0, "0"):
        timeout = pytestconfig.getini("timeout")
    assert float(timeout) > 0, "pytest-timeout must be configured so hung workers self-kill"


def test_xdist_worker_force_exit_after_session():
    assert xdist_worker_should_force_exit({"PYTEST_XDIST_WORKER": "gw0"})
    assert not xdist_worker_should_force_exit({})


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
