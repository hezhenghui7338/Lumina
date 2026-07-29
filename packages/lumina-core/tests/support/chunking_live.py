"""Shared helpers for chunking live tests."""

from __future__ import annotations

import time
from pathlib import Path

from lumina_core.chunker.chunker import chunk_text
from lumina_core.config import (
    LUMINA_SUMMARIZE_MODEL,
    RELEASE_LIVE_MAX_RETRIES,
    resolve_chunk_budget,
)
from lumina_core.summarize.segment import summarize_segment
from lumina_core.models.router import get_router
from tests.support.chunking_report import write_chunking_report

LIVE_SUMMARIZE_INPUT_CHARS = 2500
RELEASE_SUMMARIZE_INPUT_CHARS = 1500

RELEASE_FIXTURE_LIMITS: dict[str, int] = {
    # Must exceed SHORT_BOOK_CHARS (12_000) so chunker emits ≥2 segments.
    "chunk_long_novel.txt": 15_000,
    "chunk_classical.txt": 15_000,
}


def load_fixture_text(path: Path, *, max_chars: int | None = None) -> str:
    text = path.read_text(encoding="utf-8")
    if max_chars is not None:
        text = text[:max_chars]
    return text


async def run_chunk_live_gate(
    *,
    text: str,
    fixture_name: str,
    output_dir: Path,
    write_report: bool,
    enforce_min_chars: bool = True,
    summarize_input_chars: int = LIVE_SUMMARIZE_INPUT_CHARS,
    summarize_segments: tuple[int, ...] = (0, 1),
    max_summary_retries: int | None = None,
) -> Path | None:
    t0 = time.perf_counter()
    router = get_router()
    assert router is not None
    budget = resolve_chunk_budget(router.models)
    segments = chunk_text(text, budget=budget)
    assert len(segments) >= 2

    for idx in (0, 1):
        seg = segments[idx]
        assert len(seg.raw_text) <= budget.max_chars
        if enforce_min_chars and fixture_name == "chunk_long_novel.txt" and idx < len(segments) - 1:
            assert len(seg.raw_text) >= budget.min_chars

    retries = max_summary_retries
    if retries is None and summarize_segments == (0,) and not write_report:
        retries = RELEASE_LIVE_MAX_RETRIES

    summaries: dict[int, object] = {}
    for idx in summarize_segments:
        summaries[idx] = await summarize_segment(
            router,
            raw_text=segments[idx].raw_text[:summarize_input_chars],
            anchor_label=f"§段 {idx + 1}",
            max_retries=retries,
            failure_dump_path=output_dir / f"{fixture_name}_seg{idx}_raw.txt",
        )
        assert len(summaries[idx].label) <= 20

    assert segments[0].end_offset == segments[1].start_offset

    if not write_report:
        return None

    report = write_chunking_report(
        fixture_name=fixture_name,
        model=LUMINA_SUMMARIZE_MODEL,
        segments=segments,
        summaries=summaries,
        output_dir=output_dir,
        duration_seconds=time.perf_counter() - t0,
    )
    assert report.exists()
    return report
