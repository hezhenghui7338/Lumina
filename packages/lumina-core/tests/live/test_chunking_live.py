"""E2E-CHUNK-LIVE — real chunker + real Ollama summarize seg 0/1."""
from __future__ import annotations

import pytest

from lumina_core.config import RELEASE_LIVE_TIMEOUT_SECONDS

from tests.support.chunking_live import (
    RELEASE_FIXTURE_LIMITS,
    RELEASE_SUMMARIZE_INPUT_CHARS,
    load_fixture_text,
    run_chunk_live_gate,
)
from tests.support.ollama import ollama_available

_ollama_skip = pytest.mark.skipif(not ollama_available(), reason="Ollama not available")
_xdist_ollama = pytest.mark.xdist_group("ollama")

FIXTURES = ["chunk_long_novel.txt", "chunk_classical.txt"]


@pytest.mark.parametrize("fixture_name", FIXTURES)
@pytest.mark.asyncio
@_ollama_skip
@_xdist_ollama
@pytest.mark.release_live
@pytest.mark.timeout(RELEASE_LIVE_TIMEOUT_SECONDS)
async def test_e2e_chunk_release_live_smoke(fixture_name, book_fixtures_dir, live_router, output_dir):
    """Release gate: truncated fixtures + real Ollama summarize seg 0."""
    path = book_fixtures_dir / fixture_name
    if not path.exists():
        pytest.skip(f"Run scripts/generate_fixtures.py — missing {fixture_name}")
    limit = RELEASE_FIXTURE_LIMITS.get(fixture_name)
    text = load_fixture_text(path, max_chars=limit)
    await run_chunk_live_gate(
        text=text,
        fixture_name=fixture_name,
        output_dir=output_dir,
        write_report=False,
        enforce_min_chars=True,
        summarize_input_chars=RELEASE_SUMMARIZE_INPUT_CHARS,
        summarize_segments=(0,),
    )


@pytest.mark.parametrize("fixture_name", FIXTURES)
@pytest.mark.asyncio
@_ollama_skip
@_xdist_ollama
@pytest.mark.live_chunk
async def test_e2e_chunk_live_summarize_segment_0_and_1(fixture_name, book_fixtures_dir, live_router, output_dir):
    """Full fixture review — run via `just test-live` for chunking sign-off."""
    path = book_fixtures_dir / fixture_name
    if not path.exists():
        pytest.skip(f"Run scripts/generate_fixtures.py — missing {fixture_name}")
    text = load_fixture_text(path)
    report = await run_chunk_live_gate(
        text=text,
        fixture_name=fixture_name,
        output_dir=output_dir,
        write_report=True,
        enforce_min_chars=True,
        summarize_input_chars=6000,
    )
    print(f"\nChunking report: {report}")
