"""Document map extraction, hints, and LLM fallback."""

from __future__ import annotations

import asyncio
import threading

import pytest

from lumina_core.chunker.document_map import (
    extract_structure_units,
    heuristic_document_map,
    refine_document_map,
)
from lumina_core.chunker.roles import DocumentRole
from tests.support.mock_router import MockModelRouter


def test_extract_structure_units_from_section_markers():
    text = "## [§序言]\n短序\n\n## [§第一章]\n正文"
    units = extract_structure_units(text)
    assert [unit.title for unit in units] == ["序言", "第一章"]
    assert units[0].role is DocumentRole.PREFACE
    assert units[1].role is DocumentRole.BODYMATTER


def test_nested_sections_are_not_role_units():
    text = "## [§第一章]\n\n### [§一]\n\n正文\n\n## [§第二章]\n\n更多"
    units = extract_structure_units(text)
    assert [unit.title for unit in units] == ["第一章", "第二章"]


def test_structure_role_hints_override_heuristic():
    text = "## [§引言]\naaa\n\n## [§本文]\nbbb"
    units = heuristic_document_map(
        text,
        structure_roles=[
            {"title": "引言", "role": "preface"},
            {"title": "本文", "role": "bodymatter"},
        ],
    )
    assert units[0].role is DocumentRole.PREFACE
    assert units[1].role is DocumentRole.BODYMATTER


@pytest.mark.asyncio
async def test_refine_document_map_uses_llm_roles():
    text = "## [§卷首]\n序\n\n## [§第一章]\n正文"
    units = heuristic_document_map(text)
    router = MockModelRouter(
        responses={
            "summarize": {
                "units": [
                    {"idx": 0, "role": "preface", "keep_with_prev": False},
                    {"idx": 1, "role": "bodymatter", "keep_with_prev": False},
                ]
            }
        }
    )
    refined = await refine_document_map(units, router=router)
    assert refined[0].role is DocumentRole.PREFACE
    assert refined[1].role is DocumentRole.BODYMATTER
    assert router.calls


@pytest.mark.asyncio
async def test_refine_document_map_times_out_to_heuristic():
    text = "## [§序言]\n短序\n\n## [§第一章]\n正文"
    units = heuristic_document_map(text)

    class SlowRouter:
        async def complete(self, prompt: str, **kwargs):
            await asyncio.sleep(1)
            return "{}"

    refined = await refine_document_map(
        units,
        router=SlowRouter(),
        timeout=0.05,
    )
    assert [unit.role for unit in refined] == [unit.role for unit in units]


@pytest.mark.asyncio
async def test_refine_document_map_skips_when_cancelled():
    text = "## [§序言]\n短序\n\n## [§第一章]\n正文"
    units = heuristic_document_map(text)
    cancel = threading.Event()
    cancel.set()
    router = MockModelRouter(responses={"summarize": {"units": []}})
    refined = await refine_document_map(units, router=router, cancel_event=cancel)
    assert router.calls == []
    assert [unit.role for unit in refined] == [unit.role for unit in units]

def test_section_markers_ignore_bare_chapter_lines_in_toc():
    toc = "\n\n".join(f"## [§目录第{i}项]\n第{i}章" for i in range(3))
    text = toc + "\n\n## [§正文]\n内容"
    units = extract_structure_units(text)
    titles = [unit.title for unit in units]
    assert titles == ["目录第0项", "目录第1项", "目录第2项", "正文"]
    assert all(unit.role.value == "toc" for unit in units[:-1])


def test_extract_structure_units_two_megabyte_prose_is_fast():
    import time

    line = "　　这是一段没有章标的正文，用来测量结构扫描是否接近线性。\n"
    text = "第一章 开篇\n\n" + line * 70_000
    assert len(text) > 1_800_000
    started = time.monotonic()
    units = extract_structure_units(text)
    elapsed = time.monotonic() - started
    assert units and units[0].title.startswith("第一章")
    assert elapsed < 2.0, elapsed


def test_extract_structure_units_emits_progress_before_return(monkeypatch):
    from lumina_core.chunker.coop import GilYielder

    monkeypatch.setattr("lumina_core.chunker.coop.PROGRESS_INTERVAL_SECONDS", 0)
    line = "　　正文句子保证结构扫描会跨过许多行。\n"
    text = "第一章 开篇\n\n" + line * 8_000
    reports: list[tuple[int, int, str]] = []
    yielder = GilYielder(
        on_progress=lambda page, total, message: reports.append((page, total, message)),
        progress_total=len(text),
        progress_message="正在识别序言与正文结构…",
        every=2_000,
    )
    extract_structure_units(text, yielder=yielder)
    assert reports
    assert any(total > 0 and page > 0 for page, total, _ in reports)
    assert any("序言" in message or "结构" in message for _, _, message in reports)


def test_extract_structure_units_separator_line_is_fast():
    """A 62-char `=` separator in a 256k window must not stall structure scan."""
    import time

    line = "　　这是一段没有章标的正文，用来夹住分隔符行。\n"
    text = "第一章 开篇\n\n" + line * 4_000 + ("=" * 62) + "\n" + line * 4_000
    started = time.monotonic()
    units = extract_structure_units(text)
    elapsed = time.monotonic() - started
    assert units and units[0].title.startswith("第一章")
    assert elapsed < 1.0, elapsed
