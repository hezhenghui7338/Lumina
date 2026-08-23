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
