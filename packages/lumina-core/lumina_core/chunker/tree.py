"""Document structure tree built from ingest markers and optional outline hints."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from lumina_core.chunker.markers import (
    bare_chapter_title,
    clean_structure_title,
    heading_level_from_hashes,
    match_bare_chapter,
    match_heading_marker)
from lumina_core.chunker.roles import (
    DocumentRole,
    StructureRoleHint,
    classify_heading,
    parse_role)


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
    yielder=None) -> DocumentNode:
    """Nest part/chapter/section nodes from markers. Paragraphs stay out of the tree."""
    headings = _collect_headings(
        text, yielder
    )
    hints = _role_hints(structure_roles)
    book = DocumentNode(
        kind="book",
        level=-1,
        title="",
        role=DocumentRole.BODYMATTER,
        start=0,
        end=len(text))
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
            end=end)
        while len(stack) > 1 and stack[-1].level >= level:
            stack.pop()
        stack[-1].children.append(node)
        stack.append(node)

    _apply_parents(book, hints)
    return book


def heading_path_at(tree: DocumentNode, offset: int) -> list[str]:
    """Full title chain covering offset (part / chapter / section). No depth cap."""
    parts: list[str] = []
    node = tree
    while node.children:
        child = next(
            (item for item in reversed(node.children) if item.start <= offset),
            None)
        if child is None:
            break
        if child.kind in {"part", "chapter", "section"} and child.title:
            parts.append(child.title)
        node = child
    return parts


def heading_path_offset_in_span(tree: DocumentNode, start: int, end: int) -> int:
    """Prefer the deepest structure title start inside [start, end)."""
    if end <= start:
        return start
    best_offset = start
    best_depth = len(heading_path_at(tree, start))
    for node in tree.iter_nodes():
        if node is tree or not node.title:
            continue
        if not (start <= node.start < end):
            continue
        if node.kind not in {"part", "chapter", "section"}:
            continue
        depth = len(heading_path_at(tree, node.start))
        if depth >= best_depth:
            best_offset = node.start
            best_depth = depth
    return best_offset


def chapter_path_at(tree: DocumentNode, offset: int) -> str | None:
    """Title path covering offset, e.g. '第一卷 · 第三章 · 第一节'."""
    parts = heading_path_at(tree, offset)
    return " · ".join(parts) if parts else None


def heading_path_from_chapter(chapter: str | None) -> list[str]:
    """Split a stored `chapter` label into titles. Strips Lumina §."""
    name = clean_structure_title(chapter)
    if not name:
        return []
    parts: list[str] = []
    for piece in name.split(" · "):
        cleaned = clean_structure_title(piece)
        if cleaned:
            parts.append(cleaned)
    return parts


def encode_heading_path(path: list[str] | tuple[str, ...] | None) -> str | None:
    titles: list[str] = []
    for item in path or []:
        cleaned = clean_structure_title(str(item) if item is not None else "")
        if cleaned:
            titles.append(cleaned)
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
    if titles:
        return titles
    return heading_path_from_chapter(chapter)


# Outline depth cap: at most two title levels in heading_path; tertiary → label.
_SEGMENT_LABEL_MAX = 20
_YEAR_DYNASTY = (
    r"(?:明|清|道光|咸丰|同治|光绪|宣统|顺治|康熙|雍正|乾隆|嘉庆)"
    r"(?:元|[一二三四五六七八九十百零〇两]+|\d+)年"
)
_YEAR_TITLE_RE = re.compile(
    rf"^{_YEAR_DYNASTY}"
    r"(?:[正一二三四五六七八九十仲季孟冬腊]\w{0,2}月)?"
    r"$"
)
_YEAR_CORE_RE = re.compile(rf"^({_YEAR_DYNASTY})")
_PART_JUNK_RE = re.compile(r"^part\d+$", re.IGNORECASE)
_VOLUME_ZENG_RE = re.compile(r"^曾国藩全集(\d+)$")
# 第N部分 / 第N卷 / 第N篇（可带副题，如「第一卷 知性」）；亦认「卷一」。
_PART_TITLE_RE = re.compile(
    r"^(?:"
    r"第\s*[0-9一二三四五六七八九十百零〇两]+\s*(?:部分|卷|篇)"
    r"|卷\s*[0-9一二三四五六七八九十百零〇两]+"
    r")"
)
_CHAPTER_TITLE_RE = re.compile(
    r"^第\s*([0-9一二三四五六七八九十百零〇两]+)\s*章"
)
_NUMBERED_SECTION_RE = re.compile(r"^(\d+(?:\.\d+)+)\b")


def _outline_title(title: str) -> str:
    return clean_structure_title(title)


def _dedupe_consecutive(titles: list[str]) -> list[str]:
    out: list[str] = []
    for title in titles:
        if not out or out[-1] != title:
            out.append(title)
    return out


def is_part_heading(title: str) -> bool:
    """True for 部分/卷/篇 roots used as outline L1 (not 章)."""
    name = _outline_title(title)
    if not name:
        return False
    if _PART_TITLE_RE.match(name):
        # Guard: 「第一章」等不得被误认（章已由 _CHAPTER_TITLE_RE 覆盖）。
        if "章" in name.replace(" ", "") or "回" in name.replace(" ", ""):
            return False
        return True
    return re_volume(name)


def is_chapter_heading(title: str) -> bool:
    return bool(_CHAPTER_TITLE_RE.match(_outline_title(title)))


def numbered_section_key(title: str) -> tuple[int, ...] | None:
    """Parse leading ``2.1`` / ``2.2.1`` style keys; None if not numbered."""
    name = _outline_title(title)
    match = _NUMBERED_SECTION_RE.match(name)
    if not match:
        return None
    try:
        return tuple(int(part) for part in match.group(1).split("."))
    except ValueError:
        return None


def nest_flat_outline_paths(
    paths: list[tuple[str, ...]] | list[list[str]],
) -> list[tuple[str, ...]]:
    """Infer 部分/章/节 nesting when EPUB TOC is flat (empty ancestors).

    Tech-book shape: ``(部分, 章)``, ``(部分, 章, 节)``, ``(部分, 章, 节, 小节)``.
    Without a sticky 部分, nest as ``(章, 节, …)``. Front-matter stays a
    single title. Already-nested TOC rows (len>1) are kept as-is.
    """
    if not paths:
        return []
    # If any entry already has ancestors, TOC nesting worked — leave alone.
    if any(len(path) > 1 for path in paths):
        return [tuple(path) for path in paths]

    nested: list[tuple[str, ...]] = []
    part: str | None = None
    chapter: str | None = None
    section: str | None = None
    section_key: tuple[int, ...] | None = None

    def _prefix(*titles: str | None) -> tuple[str, ...]:
        return tuple(title for title in titles if title)

    for raw in paths:
        if not raw:
            continue
        leaf = _outline_title(raw[-1])
        if not leaf:
            continue
        if is_part_heading(leaf):
            part = leaf
            chapter = None
            section = None
            section_key = None
            nested.append((leaf,))
            continue
        if is_chapter_heading(leaf):
            chapter = leaf
            section = None
            section_key = None
            nested.append(_prefix(part, chapter))
            continue
        key = numbered_section_key(leaf)
        if key is not None and len(key) >= 2 and chapter is not None:
            if len(key) == 2:
                section = leaf
                section_key = key
                nested.append(_prefix(part, chapter, leaf))
            elif (
                section is not None
                and section_key is not None
                and key[: len(section_key)] == section_key
            ):
                nested.append(_prefix(part, chapter, section, leaf))
            else:
                section = leaf
                section_key = key[:2]
                nested.append(_prefix(part, chapter, leaf))
            continue
        if chapter is not None:
            if section is not None:
                nested.append(_prefix(part, chapter, section, leaf))
            else:
                nested.append(_prefix(part, chapter, leaf))
            continue
        part = None
        chapter = None
        section = None
        section_key = None
        nested.append((leaf,))
    return nested


def is_year_title(title: str) -> bool:
    name = _outline_title(title)
    return bool(name and _YEAR_TITLE_RE.match(name))


def year_core_title(title: str) -> str | None:
    """Strip optional month suffix (咸丰十年正月 → 咸丰十年)."""
    name = _outline_title(title)
    if not name:
        return None
    match = _YEAR_CORE_RE.match(name)
    return match.group(1) if match else None


def is_zeng_volume_title(title: str) -> bool:
    return bool(_VOLUME_ZENG_RE.match(_outline_title(title)))


def is_part_junk_title(title: str) -> bool:
    return bool(_PART_JUNK_RE.match(_outline_title(title)))


def compress_outline_path(
    path: list[str] | tuple[str, ...] | None,
) -> tuple[list[str], str | None]:
    """Cap heading_path at two levels; return (path2, tertiary_label).

    Tertiary becomes segment label (≤20). Deeper titles are dropped.
    Consecutive duplicate titles are collapsed.

    Preference when reconstructing tech-book TOC:
    - ``[部分/卷, 章, …]`` → ``[部分/卷, 章]`` (节/小节进 label)
    - else ``[章, 节, …]`` → ``[章, 节]``
    - 《曾国藩全集N》 keeps year as L2 when present.
    """
    cleaned = _dedupe_consecutive(
        [
            _outline_title(title)
            for title in (path or [])
            if _outline_title(title) and not is_part_junk_title(title)
        ]
    )
    if not cleaned:
        return [], None

    def _label_from(titles: list[str]) -> str | None:
        if not titles:
            return None
        text = titles[0][:_SEGMENT_LABEL_MAX]
        return text or None

    if is_zeng_volume_title(cleaned[0]):
        root = cleaned[0]
        if len(cleaned) == 1:
            return [root], None
        year_idx: int | None = None
        year: str | None = None
        for index, title in enumerate(cleaned[1:], start=1):
            core = year_core_title(title)
            if core:
                year = core
                year_idx = index
                break
        if year is not None and year_idx is not None:
            return [root, year], _label_from(cleaned[year_idx + 1 :])
        return [root, cleaned[1]], _label_from(cleaned[2:])

    part_idx = next(
        (index for index, title in enumerate(cleaned) if is_part_heading(title)),
        None,
    )
    chapter_idx = next(
        (index for index, title in enumerate(cleaned) if is_chapter_heading(title)),
        None,
    )
    # 卷/部分优先于「章+节」：否则「第一卷 · 章 · 节」会被压成「章 · 节」丢掉卷。
    if (
        part_idx is not None
        and chapter_idx is not None
        and chapter_idx > part_idx
    ):
        return [cleaned[part_idx], cleaned[chapter_idx]], _label_from(
            cleaned[chapter_idx + 1 :]
        )
    if part_idx is not None:
        root = cleaned[part_idx]
        rest = cleaned[part_idx + 1 :]
        if not rest:
            return [root], None
        return [root, rest[0]], _label_from(rest[1:])

    if chapter_idx is not None:
        chapter = cleaned[chapter_idx]
        rest = cleaned[chapter_idx + 1 :]
        if not rest:
            return [chapter], None
        section = next(
            (
                title
                for title in rest
                if (key := numbered_section_key(title)) is not None and len(key) == 2
            ),
            rest[0],
        )
        after = [title for title in rest if title != section]
        return [chapter, section], _label_from(after)

    if len(cleaned) <= 2:
        return cleaned, None
    return cleaned[:2], _label_from(cleaned[2:])


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
                char_count=max(0, body_end - node.start))
        )
        index += 1
    return units


def _collect_headings(
    text: str,
    yielder=None) -> list[tuple[int, int, str]]:
    from lumina_core.chunker.coop import GilYielder, iter_text_lines

    coop = yielder or GilYielder()
    headings: list[tuple[int, int, str]] = []
    bare: list[tuple[int, int, str]] = []
    seen: set[int] = set()
    for offset, line in iter_text_lines(text, coop):
        heading = match_heading_marker(line)
        if heading is not None:
            title = clean_structure_title(heading.group(2))
            level = heading_level_from_hashes(len(heading.group(1)))
            # TOC delta 常把后续章写成与卷同级的 ##；卷/部分标题强制 L0，
            # 使同卷后续 ## 章仍挂在卷下（人性论：第一卷 → 第二/三/四章）。
            if title and (is_part_heading(title) or re_volume(title)):
                level = 0
            elif title and is_chapter_heading(title) and level > 1:
                level = 1
            headings.append((offset, level, title))
            seen.add(offset)
            continue
        chapter = match_bare_chapter(line)
        if chapter is not None and offset not in seen:
            title = bare_chapter_title(chapter)
            if is_part_heading(title) or re_volume(title):
                level = 0
            elif is_chapter_heading(title):
                level = 1
            else:
                level = 1
            bare.append((offset, level, title))
    if not any(level <= 1 for _, level, _ in headings):
        headings.extend(bare)
    headings.sort(key=lambda item: item[0])
    return headings


def re_volume(title: str) -> bool:
    """Bare/hash volume-like titles: 第N卷/部/篇…, not 章/回."""
    compact = _outline_title(title).replace(" ", "")
    if not compact:
        return False
    if "章" in compact or "回" in compact:
        return False
    if compact.startswith("第") and any(
        token in compact for token in ("卷", "部", "篇")
    ):
        return True
    return bool(re.match(r"^卷[0-9一二三四五六七八九十百零〇两]+", compact))


def _role_hints(
    structure_roles: list[dict[str, Any] | StructureRoleHint] | None) -> list[StructureRoleHint]:
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
                    role=parse_role(str(hint.get("role") or "")))
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
