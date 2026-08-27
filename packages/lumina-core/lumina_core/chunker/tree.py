"""Document structure tree built from ingest markers and optional outline hints."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from lumina_core.chunker.markers import (
    bare_chapter_title,
    clean_structure_title,
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


@dataclass
class DocumentNode:
    kind: str  # book | part | chapter | section
    level: int
    title: str
    role: DocumentRole
    start: int
    end: int
    children: list[DocumentNode] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "level": self.level,
            "title": self.title,
            "role": self.role.value,
            "start": self.start,
            "end": self.end,
            "children": [child.to_dict() for child in self.children],
        }

    def iter_nodes(self) -> list[DocumentNode]:
        out = [self]
        for child in self.children:
            out.extend(child.iter_nodes())
        return out


def build_document_tree(
    text: str,
    *,
    structure_roles: list[dict[str, Any] | StructureRoleHint] | None = None,
    yielder=None,
) -> DocumentNode:
    """Nest part/chapter/section nodes from markers. Paragraphs stay out of the tree."""
    headings = _collect_headings(text, yielder)
    hints = _role_hints(structure_roles)
    book = DocumentNode(
        kind="book",
        level=-1,
        title="",
        role=DocumentRole.BODYMATTER,
        start=0,
        end=len(text),
    )
    if not headings:
        return book

    stack: list[DocumentNode] = [book]
    for index, (start, level, title) in enumerate(headings):
        end = headings[index + 1][0] if index + 1 < len(headings) else len(text)
        kind = "part" if level <= 0 else "chapter" if level == 1 else "section"
        role = _role_for_title(title, hints)
        node = DocumentNode(
            kind=kind,
            level=level,
            title=title,
            role=role,
            start=start,
            end=end,
        )
        while len(stack) > 1 and stack[-1].level >= level:
            stack.pop()
        stack[-1].children.append(node)
        stack.append(node)

    _apply_parents(book, hints)
    return book


def heading_path_at(tree: DocumentNode, offset: int) -> list[str]:
    """Part then chapter titles covering offset, at most 2. Sections do not join."""
    parts: list[str] = []
    node = tree
    while node.children:
        child = next(
            (item for item in reversed(node.children) if item.start <= offset),
            None,
        )
        if child is None:
            break
        if child.kind in {"part", "chapter"} and child.title:
            parts.append(child.title)
        node = child
        if child.kind == "chapter" or len(parts) >= 2:
            break
    if parts:
        return parts[:2]
    for item in reversed(tree.iter_nodes()):
        if (
            item.kind == "section"
            and item.title
            and item.start <= offset < item.end
        ):
            return [item.title]
    return []


def chapter_path_at(tree: DocumentNode, offset: int) -> str | None:
    """Nearest part/chapter title path covering offset, e.g. '第一卷 · 第三章'.

    Sections stay in the tree but do not split reader chapter groups.
    """
    parts = heading_path_at(tree, offset)
    return " · ".join(parts) if parts else None


def heading_path_from_chapter(chapter: str | None) -> list[str]:
    """Split a stored `chapter` label into at most 2 titles. Strips Lumina §."""
    name = clean_structure_title(chapter)
    if not name:
        return []
    parts: list[str] = []
    for piece in name.split(" · "):
        cleaned = clean_structure_title(piece)
        if cleaned:
            parts.append(cleaned)
        if len(parts) >= 2:
            break
    return parts


def encode_heading_path(path: list[str] | tuple[str, ...] | None) -> str | None:
    titles: list[str] = []
    for item in path or []:
        cleaned = clean_structure_title(str(item) if item is not None else "")
        if cleaned:
            titles.append(cleaned)
        if len(titles) >= 2:
            break
    if not titles:
        return None
    return json.dumps(titles, ensure_ascii=False)


def decode_heading_path(raw: Any, *, chapter: str | None = None) -> list[str]:
    parsed: list[Any] | None = None
    if isinstance(raw, list):
        parsed = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            loaded = None
        if isinstance(loaded, list):
            parsed = loaded
    titles: list[str] = []
    if parsed:
        for item in parsed:
            cleaned = clean_structure_title(str(item) if item is not None else "")
            if cleaned:
                titles.append(cleaned)
            if len(titles) >= 2:
                break
    if titles:
        return titles
    return heading_path_from_chapter(chapter)


def tree_to_structure_units(tree: DocumentNode):
    """Chapter/part nodes only — sections are not role units."""
    from lumina_core.chunker.document_map import StructureUnit

    units: list[StructureUnit] = []
    index = 0
    for node in tree.iter_nodes():
        if node.kind not in {"part", "chapter"}:
            continue
        if node is tree:
            continue
        body_end = node.end
        head = ""
        tail = ""
        # filled by caller if needed; document_map extract still owns head/tail
        units.append(
            StructureUnit(
                index=index,
                start=node.start,
                title=node.title,
                role=node.role,
                head=head,
                tail=tail,
                char_count=max(0, body_end - node.start),
            )
        )
        index += 1
    return units


def _collect_headings(text: str, yielder=None) -> list[tuple[int, int, str]]:
    from lumina_core.chunker.coop import GilYielder, iter_text_lines

    coop = yielder or GilYielder()
    headings: list[tuple[int, int, str]] = []
    bare: list[tuple[int, int, str]] = []
    seen: set[int] = set()
    for offset, line in iter_text_lines(text, coop):
        heading = match_heading_marker(line)
        if heading is not None:
            headings.append(
                (
                    offset,
                    heading_level_from_hashes(len(heading.group(1))),
                    clean_structure_title(heading.group(2)),
                )
            )
            seen.add(offset)
            continue
        chapter = match_bare_chapter(line)
        if chapter is not None and offset not in seen:
            title = bare_chapter_title(chapter)
            level = 0 if re_volume(title) else 1
            bare.append((offset, level, title))
    if not any(level <= 1 for _, level, _ in headings):
        headings.extend(bare)
    headings.sort(key=lambda item: item[0])
    return headings


def re_volume(title: str) -> bool:
    compact = title.replace(" ", "")
    return bool(
        compact.startswith("第") and any(token in compact for token in ("卷", "部", "篇"))
        and "章" not in compact
        and "回" not in compact
    )


def _role_hints(
    structure_roles: list[dict[str, Any] | StructureRoleHint] | None,
) -> list[StructureRoleHint]:
    if not structure_roles:
        return []
    parsed: list[StructureRoleHint] = []
    for hint in structure_roles:
        if isinstance(hint, StructureRoleHint):
            parsed.append(hint)
        elif isinstance(hint, dict):
            parsed.append(
                StructureRoleHint(
                    title=str(hint.get("title") or ""),
                    role=parse_role(str(hint.get("role") or "")),
                )
            )
    return parsed


def _role_for_title(title: str, hints: list[StructureRoleHint]) -> DocumentRole:
    by_title = {hint.title.strip(): hint.role for hint in hints if hint.title.strip()}
    if title.strip() in by_title:
        return by_title[title.strip()]
    return classify_heading(title)


def _apply_parents(book: DocumentNode, hints: list[StructureRoleHint]) -> None:
    """Wrap consecutive chapters that share a parent title from ingest hints."""
    # Parent wrapping is encoded in heading levels when ingest emits # vs ##.
    _ = hints
    _ = book
