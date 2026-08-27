"""Heading / page markers injected by ingest. Shared by chunker and loaders.

Chapter-level markers stay ``## [§title]`` (HARD). Nested headings use more
hashes so they are STRONG, not sibling chapters. Page markers are anchors only.
"""

from __future__ import annotations

import re

HEADING_MARKER = re.compile(r"^(#{1,6}) \[§(.+)\][ \t]*$", re.MULTILINE)
PAGE_MARKER = re.compile(r"^## \[p\.(\d+)(?:\s+无文本)?\][ \t]*$", re.MULTILINE)
# TXT novels glue separator runs onto the title line:
# 「————————————第四章崖高人远」 / 「── 第四章 崖高人远 ──」
# Do not include brackets/parens — 「（第三回完）」 is not a chapter start.
_DASH_CHARS = r"\-–—―─━═＝－_=~*"
_DECOR_CHARS = rf"＊★☆※·•〜～{_DASH_CHARS}"
# One bounded run. Repeating `(blank* dashes+ blank*){1,8}` ReDoS on `====` lines.
_HEADING_DECOR = rf"[ \t　]*[{_DECOR_CHARS}]{{1,40}}[ \t　]*"
# Title-like 第N章/节 lines only — not a paragraph that happens to start with 第一章.
# Whitespace title: 「第七章 重阳遗刻」. Glued short title: 「第七章初始」.
# Optional name must not swallow trailing separator dashes; keep 「·」 in titles.
_ORDINAL_TITLE = (
    r"第[零一二三四五六七八九十百千\d]+[章节篇回]"
    rf"(?:\s+[^\n。！？{_DASH_CHARS}]{{1,40}}|[^\n。！？\s，、；{_DASH_CHARS}]{{1,16}})?"
)
_BARE_TITLE = rf"(?:{_ORDINAL_TITLE}|§\s*[^\n。！？{_DASH_CHARS}]{{1,80}})"
BARE_CHAPTER = re.compile(
    rf"^[ \t　]*(?:{_HEADING_DECOR})?({_BARE_TITLE})(?:{_HEADING_DECOR})?$",
    re.MULTILINE,
)
# Whole-line chapter titles only. Longer lines cannot match `$` and must not run the regex.
CHAPTER_LINE_MAX_CHARS = 120
_HASH_HEADING_MAX_CHARS = 200
_DECOR_PREFIX = frozenset(_DECOR_CHARS.replace("\\", ""))
_STRUCTURE_PREFIX = frozenset("#§第") | _DECOR_PREFIX

# Atom starts: headings, pages, traditional chapter titles, markdown titles.
STRUCTURE_LINE = re.compile(
    rf"^(?:#{{1,6}} \[§.+\]|## \[p\.\d+(?:\s+无文本)?\]|"
    rf"(?:{_HEADING_DECOR})?{_BARE_TITLE}(?:{_HEADING_DECOR})?|"
    rf"#{{1,6}}\s+.{{1,80}})$"
)
PAGE_LINE = re.compile(r"^## \[p\.\d+(?:\s+无文本)?\]$")
HASH_HEADING = re.compile(r"^(#{1,6}) \[§(.+)\]$")
MD_TITLE = re.compile(r"^(#{1,6})\s+(.+)$")


def _lstrip_line(line: str) -> str:
    return line.lstrip(" \t　")


def _has_chapter_token(stripped: str) -> bool:
    """Bare chapter regex cannot match without 第N章 or §; skip decor-only separators."""
    return "第" in stripped or "§" in stripped


def may_be_chapter_line(line: str) -> bool:
    """Cheap reject: short line, starts like a title, and contains 第 or §."""
    stripped = _lstrip_line(line).rstrip()
    if not stripped or len(stripped) > CHAPTER_LINE_MAX_CHARS:
        return False
    if not _has_chapter_token(stripped):
        return False
    return stripped[0] in _STRUCTURE_PREFIX and stripped[0] != "#"


def may_be_hash_heading_line(line: str) -> bool:
    stripped = _lstrip_line(line).rstrip()
    return bool(stripped) and stripped[0] == "#" and len(stripped) <= _HASH_HEADING_MAX_CHARS


def match_heading_marker(line: str) -> re.Match[str] | None:
    if not may_be_hash_heading_line(line):
        return None
    return HEADING_MARKER.match(line)


def match_bare_chapter(line: str) -> re.Match[str] | None:
    """Match a whole-line 第N章 title. Never run the regex on long prose."""
    if not may_be_chapter_line(line):
        return None
    return BARE_CHAPTER.match(line)


def match_structure_line(line: str) -> re.Match[str] | None:
    stripped = _lstrip_line(line).rstrip()
    if not stripped:
        return None
    if stripped[0] == "#":
        if len(stripped) > _HASH_HEADING_MAX_CHARS:
            return None
    elif (
        len(stripped) > CHAPTER_LINE_MAX_CHARS
        or stripped[0] not in _STRUCTURE_PREFIX
        or not _has_chapter_token(stripped)
    ):
        return None
    return STRUCTURE_LINE.match(stripped)


def clean_structure_title(title: str | None) -> str:
    """Strip format-native section signs from TOC / heading titles.

    Lumina markers stay ``## [§{cleaned}]``. Does not strip mid-title §.
    """
    text = (title or "").strip()
    while text.startswith("§"):
        text = text[1:].lstrip()
    while text.endswith("§"):
        text = text[:-1].rstrip()
    return text.strip()


def lumina_chapter_label(title: str | None) -> str | None:
    """User-visible chapter field: one Lumina § prefix, never stacked."""
    name = clean_structure_title(title)
    if not name:
        return None
    return f"§{name}"


def heading_marker(title: str, level: int) -> str:
    """Render a structure marker. level 0 = part, 1 = chapter, 2+ = section."""
    cleaned = clean_structure_title(title)
    if level <= 0:
        hashes = 1
    else:
        hashes = min(6, level + 1)
    return f"{'#' * hashes} [§{cleaned}]"


def heading_level_from_hashes(hashes: int) -> int:
    """Invert heading_marker: 1 hash → part 0, 2 hashes → chapter 1."""
    return max(0, hashes - 1)


def bare_chapter_title(match: re.Match[str]) -> str:
    """Chapter title without glued separator runs or source §."""
    captured = match.group(1) if match.lastindex else match.group(0)
    return clean_structure_title(captured)


def parse_heading_line(stripped: str) -> tuple[int, str] | None:
    """Return (level, title) for a heading line, or None."""
    if not stripped:
        return None
    if stripped[0] == "#":
        if len(stripped) > _HASH_HEADING_MAX_CHARS:
            return None
        match = HASH_HEADING.match(stripped)
        if match:
            return (
                heading_level_from_hashes(len(match.group(1))),
                clean_structure_title(match.group(2)),
            )
        if PAGE_LINE.match(stripped):
            return None
        match = MD_TITLE.match(stripped)
        if match and not stripped.startswith("## ["):
            return (
                heading_level_from_hashes(len(match.group(1))),
                clean_structure_title(match.group(2)),
            )
        return None
    if PAGE_LINE.match(stripped):
        return None
    match = match_bare_chapter(stripped)
    if match:
        title = bare_chapter_title(match)
        if "章" in title or "回" in title or title.lower().startswith("chapter"):
            return 1, title
        if "节" in title:
            return 2, title
        if "卷" in title or "部" in title or "篇" in title:
            return 0, title
        return 1, title
    return None


def is_page_line(stripped: str) -> bool:
    return bool(PAGE_LINE.match(stripped))


def is_hash_heading_line(stripped: str) -> bool:
    """True for ``# [§…]`` / markdown titles, not bare 第N章 or page anchors."""
    if not stripped or stripped[0] != "#" or len(stripped) > _HASH_HEADING_MAX_CHARS:
        return False
    if HASH_HEADING.match(stripped):
        return True
    if PAGE_LINE.match(stripped) or stripped.startswith("## ["):
        return False
    return bool(MD_TITLE.match(stripped))


def is_hard_heading_line(stripped: str) -> bool:
    """Part/chapter markers and traditional 第N章 lines (not page, not h3+)."""
    parsed = parse_heading_line(stripped)
    if parsed is None:
        return False
    return parsed[0] <= 1
