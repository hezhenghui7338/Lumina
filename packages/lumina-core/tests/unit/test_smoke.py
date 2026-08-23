"""Smoke tests — verify Phase 0 infra."""

def test_import_lumina_core():
    import lumina_core
    from lumina_core.config import CORE_VERSION

    assert lumina_core.__version__ == CORE_VERSION

def test_pytest_markers_registered():
    import pytest
    for name in ("e2e", "live", "live_chunk", "release_live", "perf"):
        assert hasattr(pytest.mark, name)
