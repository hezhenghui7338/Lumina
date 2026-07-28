"""E2E-CHUNK-LIVE — real chunker + real Ollama summarize seg 0/1."""
from __future__ import annotations
import time
import pytest
from lumina_core.chunker.chunker import chunk_text
from lumina_core.config import CHUNK_MAX_CHARS, CHUNK_MIN_CHARS, LUMINA_SUMMARIZE_MODEL
from lumina_core.models.router import get_router
from lumina_core.summarize.schema import parse_segment_summary
from tests.support.chunking_report import write_chunking_report
from tests.support.ollama import ollama_available

SUMMARIZE_PROMPT = """请为以下段落生成 JSON 摘要，字段：sentences(最多3句), bullets(3-7条), label(≤20字), anchor。
段落：
{text}"""

pytestmark = [pytest.mark.live_chunk, pytest.mark.skipif(not ollama_available(), reason="Ollama not available")]

@pytest.mark.parametrize("fixture_name", ["chunk_long_novel.txt", "chunk_classical.txt"])
@pytest.mark.asyncio
async def test_e2e_chunk_live_summarize_segment_0_and_1(fixture_name, book_fixtures_dir, live_router, output_dir):
    path = book_fixtures_dir / fixture_name
    if not path.exists():
        pytest.skip(f"Run scripts/generate_fixtures.py — missing {fixture_name}")
    t0 = time.perf_counter()
    segments = chunk_text(path.read_text(encoding="utf-8"))
    assert len(segments) >= 2
    router = get_router()
    summaries = {}
    for idx in (0, 1):
        seg = segments[idx]
        if idx < len(segments) - 1:
            assert CHUNK_MIN_CHARS <= len(seg.raw_text) <= CHUNK_MAX_CHARS
        raw = await router.complete(SUMMARIZE_PROMPT.format(text=seg.raw_text[:6000]), profile="summarize", json_mode=True)
        summaries[idx] = parse_segment_summary(raw)
        assert len(summaries[idx].label) <= 20
    assert segments[0].end_offset <= segments[1].start_offset
    report = write_chunking_report(fixture_name=fixture_name, model=LUMINA_SUMMARIZE_MODEL, segments=segments, summaries=summaries, output_dir=output_dir, duration_seconds=time.perf_counter() - t0)
    assert report.exists()
    print(f"\nChunking report: {report}")
