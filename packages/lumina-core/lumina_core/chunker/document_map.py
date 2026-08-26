"""One-shot document map: structure units + optional LLM role refinement."""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, replace
from typing import Any, Protocol

from pydantic import BaseModel, Field, field_validator

from lumina_core.chunker.markers import (
    bare_chapter_title,
    heading_level_from_hashes,
    match_bare_chapter,
    match_heading_marker,
)
from lumina_core.chunker.roles import (
    DocumentRole,
    StructureRoleHint,
    classify_heading,
    parse_role,
)
from lumina_core.chunker.semantic import TextAtom
from lumina_core.config import DOCUMENT_MAP_TIMEOUT_SECONDS, PromptsConfig, load_prompts_config
from lumina_core.models.router import parse_json_response
from lumina_core.prompts_defaults import DEFAULT_DOCUMENT_MAP

logger = logging.getLogger(__name__)

_HEAD_CHARS = 180
_TAIL_CHARS = 60
_MAX_UNITS_FOR_LLM = 80


class Completer(Protocol):
    async def complete(
        self,
        prompt: str,
        *,
        profile: str = "summarize",
        json_mode: bool = False,
        **kwargs: Any,
    ) -> str: ...


@dataclass(frozen=True)
class StructureUnit:
    index: int
    start: int
    title: str
    role: DocumentRole
    keep_with_prev: bool = False
    head: str = ""
    tail: str = ""
    char_count: int = 0


class LlmUnit(BaseModel):
    idx: int
    role: DocumentRole
    keep_with_prev: bool = False

    @field_validator("role", mode="before")
    @classmethod
    def coerce_role(cls, value: object) -> DocumentRole:
        if isinstance(value, DocumentRole):
            return value
        return parse_role(str(value) if value is not None else None)


class LlmMap(BaseModel):
    units: list[LlmUnit] = Field(default_factory=list)


def extract_structure_units(text: str, yielder=None) -> list[StructureUnit]:
    """Collect part/chapter markers. Nested ### sections are not role units."""
    from lumina_core.chunker.coop import GilYielder, iter_text_lines

    coop = yielder or GilYielder()
    coop.ensure_total(len(text))
    coop.set_stage("正在识别序言与正文结构…", reset=False)
    starts: list[tuple[int, str]] = []
    seen: set[int] = set()
    bare: list[tuple[int, str]] = []
    for offset, line in iter_text_lines(text, coop):
        heading = match_heading_marker(line)
        if heading is not None:
            level = heading_level_from_hashes(len(heading.group(1)))
            if level <= 1:
                starts.append((offset, heading.group(2).strip()))
                seen.add(offset)
            continue
        chapter = match_bare_chapter(line)
        if chapter is not None and offset not in seen:
            bare.append((offset, bare_chapter_title(chapter)))
    if not starts:
        starts = bare
    starts.sort(key=lambda item: item[0])
    if not starts:
        return []

    units: list[StructureUnit] = []
    for index, ((start, title), nxt) in enumerate(
        zip(starts, starts[1:] + [(len(text), "")])
    ):
        end = nxt[0]
        char_count = end - start
        head = text[start : start + min(_HEAD_CHARS, char_count)]
        tail = (
            text[end - _TAIL_CHARS : end] if char_count > _HEAD_CHARS else ""
        )
        units.append(
            StructureUnit(
                index=index,
                start=start,
                title=title,
                role=classify_heading(title),
                head=head,
                tail=tail,
                char_count=char_count,
            )
        )
        coop.bump(char_count)
    return units


def apply_structure_hints(
    units: list[StructureUnit],
    hints: list[StructureRoleHint] | list[dict[str, Any]] | None,
) -> list[StructureUnit]:
    """Overlay ingest-provided landmark/outline roles by index then title."""
    if not units or not hints:
        return units
    parsed: list[StructureRoleHint] = []
    for hint in hints:
        if isinstance(hint, StructureRoleHint):
            parsed.append(hint)
        elif isinstance(hint, dict):
            parsed.append(StructureRoleHint.model_validate(hint))
    by_index = {i: hint for i, hint in enumerate(parsed)}
    by_title = {hint.title.strip(): hint.role for hint in parsed if hint.title.strip()}
    out: list[StructureUnit] = []
    for unit in units:
        role = unit.role
        indexed = by_index.get(unit.index)
        if indexed is not None:
            role = indexed.role
        elif unit.title.strip() in by_title:
            role = by_title[unit.title.strip()]
        out.append(replace(unit, role=role) if role is not unit.role else unit)
    return out


def apply_keep_with_prev(units: list[StructureUnit]) -> list[StructureUnit]:
    if not units:
        return units
    out: list[StructureUnit] = [units[0]]
    for unit in units[1:]:
        if unit.keep_with_prev:
            out.append(replace(unit, role=out[-1].role))
        else:
            out.append(unit)
    return out


def assign_roles_to_atoms(
    atoms: list[TextAtom],
    units: list[StructureUnit],
) -> list[TextAtom]:
    if not atoms:
        return atoms
    if not units:
        return [replace(atom, role=DocumentRole.BODYMATTER) for atom in atoms]

    first_start = units[0].start
    prefix_role = (
        DocumentRole.FRONT
        if units[0].role is not DocumentRole.BODYMATTER
        else DocumentRole.BODYMATTER
    )
    out: list[TextAtom] = []
    cursor = 0
    for atom in atoms:
        while cursor + 1 < len(units) and atom.start >= units[cursor + 1].start:
            cursor += 1
        role = prefix_role if atom.start < first_start else units[cursor].role
        out.append(replace(atom, role=role) if atom.role is not role else atom)
    return out


def _units_payload(units: list[StructureUnit]) -> str:
    lines: list[str] = []
    for unit in units[:_MAX_UNITS_FOR_LLM]:
        lines.append(
            f"{unit.index}\t{unit.role.value}\t{unit.char_count}\t{unit.title}\t"
            f"{unit.head.replace(chr(10), ' ')}\t{unit.tail.replace(chr(10), ' ')}"
        )
    return "\n".join(lines)


def heuristic_document_map(
    text: str,
    *,
    structure_roles: list[dict[str, Any]] | None = None,
    yielder=None,
) -> list[StructureUnit]:
    return apply_structure_hints(
        extract_structure_units(text, yielder=yielder), structure_roles
    )


async def refine_document_map(
    units: list[StructureUnit],
    *,
    router: Completer | None,
    prompts: PromptsConfig | None = None,
    cancel_event: threading.Event | None = None,
    timeout: float = DOCUMENT_MAP_TIMEOUT_SECONDS,
) -> list[StructureUnit]:
    """Optional LLM pass. Timeouts and errors fall back to the heuristic map."""
    if router is None or not units:
        return units
    if cancel_event is not None and cancel_event.is_set():
        return units
    cfg = prompts or load_prompts_config()
    template = getattr(cfg, "document_map", None) or DEFAULT_DOCUMENT_MAP
    prompt = template.format(units=_units_payload(units))

    async def _call() -> str:
        return await router.complete(prompt, profile="summarize", json_mode=True)

    try:
        raw = await asyncio.wait_for(_call(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.info("document map LLM timed out; using heuristic roles")
        return units
    except Exception:
        logger.warning("document map LLM failed; using heuristic roles", exc_info=True)
        return units
    if cancel_event is not None and cancel_event.is_set():
        return units
    try:
        data = parse_json_response(raw) if isinstance(raw, str) else raw
        parsed = LlmMap.model_validate(data)
    except Exception:
        logger.warning("document map response invalid; using heuristic roles", exc_info=True)
        return units
    by_idx = {item.idx: item for item in parsed.units}
    refined: list[StructureUnit] = []
    for unit in units:
        item = by_idx.get(unit.index)
        if item is None:
            refined.append(unit)
            continue
        refined.append(replace(unit, role=item.role, keep_with_prev=item.keep_with_prev))
    return apply_keep_with_prev(refined)
