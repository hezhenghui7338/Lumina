"""Smoke tests — verify Phase 0 infra."""

def test_import_lumina_core():
    import lumina_core
    assert lumina_core.__version__ == "0.6.0"

def test_pytest_markers_registered():
    import pytest
    for name in ("e2e", "live", "live_chunk", "release_live", "perf"):
        assert hasattr(pytest.mark, name)
