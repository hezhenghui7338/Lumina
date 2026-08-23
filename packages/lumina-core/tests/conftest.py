"""Shared pytest fixtures."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

import pytest

# Limit native pools before any test imports RapidOCR/onnxruntime.
# Unbounded Eigen threads can deadlock pytest-xdist worker teardown.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("ORT_INTRA_OP_NUM_THREADS", "1")
os.environ.setdefault("ORT_INTER_OP_NUM_THREADS", "1")

from lumina_core.models.router import set_router
from tests.support.mock_router import MockModelRouter, load_json_fixture

FIXTURES_DIR = Path(__file__).parent / "fixtures"
LLM_FIXTURES = FIXTURES_DIR / "llm"
BOOK_FIXTURES = FIXTURES_DIR / "books"
REPO_OUTPUT = Path(__file__).resolve().parents[3] / "tests" / "output"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def book_fixtures_dir() -> Path:
    return BOOK_FIXTURES


@pytest.fixture
def llm_fixtures_dir() -> Path:
    return LLM_FIXTURES


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    """Prefer repo tests/output when writable; else pytest tmp."""
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    try:
        base = REPO_OUTPUT / worker if worker else REPO_OUTPUT
        base.mkdir(parents=True, exist_ok=True)
        return base
    except OSError:
        return tmp_path / "output"


@pytest.fixture
def sample_book_text(book_fixtures_dir: Path) -> str:
    return (book_fixtures_dir / "sample.txt").read_text(encoding="utf-8")


@pytest.fixture
def mock_router():
    """Inject MockModelRouter — used by default e2e/unit tests."""
    router = MockModelRouter(
        responses={
            "summarize": load_json_fixture(LLM_FIXTURES / "summary_segment0.json"),
            "chat": load_json_fixture(LLM_FIXTURES / "chat_with_citation.json"),
            "translate": "译文 fixture 示例文本。",
        }
    )
    set_router(router)
    yield router
    set_router(None)


@pytest.fixture
def live_router():
    """Real Ollama router — only for @live_chunk / @live tests."""
    from lumina_core.config import LUMINA_SUMMARIZE_MODEL, OLLAMA_BASE_URL
    from lumina_core.models.router import OllamaRouter

    router = OllamaRouter(
        OLLAMA_BASE_URL,
        models={
            "summarize": LUMINA_SUMMARIZE_MODEL,
            "chat": LUMINA_SUMMARIZE_MODEL,
            "translate": LUMINA_SUMMARIZE_MODEL,
        },
    )
    set_router(router)
    yield router
    set_router(None)


@pytest.fixture(autouse=True)
def _reset_router_between_tests(request):
    """Ensure live tests don't leak router into mock tests."""
    yield
    set_router(None)


def xdist_worker_should_force_exit(environ: Mapping[str, str]) -> bool:
    """xdist workers that loaded ORT can hang in session teardown; force-exit them."""
    return bool(environ.get("PYTEST_XDIST_WORKER"))


@pytest.hookimpl(hookwrapper=True, trylast=True)
def pytest_sessionfinish(session, exitstatus):
    yield
    if not xdist_worker_should_force_exit(os.environ):
        return
    os._exit(int(exitstatus))
