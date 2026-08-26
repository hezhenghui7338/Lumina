"""Document-role taxonomy for professional segmentation.

Roles live on atoms / structure units only — never written into raw_text.
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, field_validator


class DocumentRole(str, Enum):
    COPYRIGHT = "copyright"
    DEDICATION = "dedication"
    TOC = "toc"
    PREFACE = "preface"
    FOREWORD = "foreword"
    INTRODUCTION = "introduction"
    PROLOGUE = "prologue"
    FRONT = "front"
    BODYMATTER = "bodymatter"
    EPILOGUE = "epilogue"
    APPENDIX = "appendix"
    NOTES = "notes"
    INDEX = "index"
    OTHER = "other"


ROLE_FAMILY: dict[DocumentRole, str] = {
    DocumentRole.COPYRIGHT: "front",
    DocumentRole.DEDICATION: "front",
    DocumentRole.TOC: "front",
    DocumentRole.PREFACE: "front",
    DocumentRole.FOREWORD: "front",
    DocumentRole.INTRODUCTION: "front",
    DocumentRole.PROLOGUE: "front",
    DocumentRole.FRONT: "front",
    DocumentRole.BODYMATTER: "body",
    DocumentRole.EPILOGUE: "back",
    DocumentRole.APPENDIX: "back",
    DocumentRole.NOTES: "back",
    DocumentRole.INDEX: "back",
    DocumentRole.OTHER: "other",
}

ALLOWED_ROLES = frozenset(role.value for role in DocumentRole)

_EPUB_LANDMARK_ALIASES: dict[str, DocumentRole] = {
    "cover": DocumentRole.OTHER,
    "titlepage": DocumentRole.COPYRIGHT,
    "title-page": DocumentRole.COPYRIGHT,
    "copyright-page": DocumentRole.COPYRIGHT,
    "copyright": DocumentRole.COPYRIGHT,
    "colophon": DocumentRole.COPYRIGHT,
    "dedication": DocumentRole.DEDICATION,
    "toc": DocumentRole.TOC,
    "text": DocumentRole.BODYMATTER,
    "bodymatter": DocumentRole.BODYMATTER,
    "body-matter": DocumentRole.BODYMATTER,
    "preface": DocumentRole.PREFACE,
    "foreword": DocumentRole.FOREWORD,
    "introduction": DocumentRole.INTRODUCTION,
    "prologue": DocumentRole.PROLOGUE,
    "epilogue": DocumentRole.EPILOGUE,
    "afterword": DocumentRole.EPILOGUE,
    "appendix": DocumentRole.APPENDIX,
    "bibliography": DocumentRole.APPENDIX,
    "glossary": DocumentRole.APPENDIX,
    "notes": DocumentRole.NOTES,
    "footnotes": DocumentRole.NOTES,
    "endnotes": DocumentRole.NOTES,
    "index": DocumentRole.INDEX,
    "loi": DocumentRole.TOC,
    "lot": DocumentRole.TOC,
}

_FRONT_EXACT = {
    "序": DocumentRole.PREFACE,
    "序言": DocumentRole.PREFACE,
    "前言": DocumentRole.PREFACE,
    "自序": DocumentRole.PREFACE,
    "译者序": DocumentRole.PREFACE,
    "再版序": DocumentRole.PREFACE,
    "原序": DocumentRole.PREFACE,
    "代序": DocumentRole.PREFACE,
    "绪言": DocumentRole.PREFACE,
    "绪论": DocumentRole.INTRODUCTION,
    "楔子": DocumentRole.PROLOGUE,
    "引子": DocumentRole.PROLOGUE,
    "卷首": DocumentRole.FRONT,
    "序章": DocumentRole.PROLOGUE,
    "献词": DocumentRole.DEDICATION,
    "献辞": DocumentRole.DEDICATION,
    "目录": DocumentRole.TOC,
    "版权": DocumentRole.COPYRIGHT,
    "版权页": DocumentRole.COPYRIGHT,
    "版权信息": DocumentRole.COPYRIGHT,
    "出版说明": DocumentRole.COPYRIGHT,
    "preface": DocumentRole.PREFACE,
    "foreword": DocumentRole.FOREWORD,
    "prologue": DocumentRole.PROLOGUE,
    "introduction": DocumentRole.INTRODUCTION,
    "dedication": DocumentRole.DEDICATION,
    "contents": DocumentRole.TOC,
    "table of contents": DocumentRole.TOC,
    "copyright": DocumentRole.COPYRIGHT,
}
_BACK_EXACT = {
    "后记": DocumentRole.EPILOGUE,
    "跋": DocumentRole.EPILOGUE,
    "结语": DocumentRole.EPILOGUE,
    "附录": DocumentRole.APPENDIX,
    "索引": DocumentRole.INDEX,
    "注释": DocumentRole.NOTES,
    "epilogue": DocumentRole.EPILOGUE,
    "afterword": DocumentRole.EPILOGUE,
    "appendix": DocumentRole.APPENDIX,
    "index": DocumentRole.INDEX,
}
_BODY_HEADING = re.compile(
    r"^(?:第[零一二三四五六七八九十百千\d]+[章节篇回]|chapter\s+\d+|正文)",
    re.IGNORECASE,
)
_STRIP_MARKER = re.compile(r"^##\s*\[§(.+)\]\s*$")


def normalize_heading(value: str) -> str:
    stripped = (value or "").strip()
    match = _STRIP_MARKER.match(stripped)
    if match:
        stripped = match.group(1).strip()
    stripped = stripped.lstrip("#§ ").strip()
    return stripped


def parse_role(value: str | None) -> DocumentRole:
    if not value:
        return DocumentRole.OTHER
    cleaned = value.strip().lower().replace("_", "-")
    try:
        return DocumentRole(cleaned)
    except ValueError:
        return _EPUB_LANDMARK_ALIASES.get(cleaned, DocumentRole.OTHER)


def landmark_role(epub_type: str | None) -> DocumentRole | None:
    if not epub_type:
        return None
    return _EPUB_LANDMARK_ALIASES.get(epub_type.strip().lower().replace("_", "-"))


def classify_heading(title: str) -> DocumentRole:
    """Heuristic role from a chapter / spine / outline title."""
    heading = normalize_heading(title)
    if not heading:
        return DocumentRole.OTHER
    compact = re.sub(r"\s+", "", heading)
    lower = heading.lower().strip()
    exact = _FRONT_EXACT.get(compact) or _FRONT_EXACT.get(lower)
    if exact:
        return exact
    back = _BACK_EXACT.get(compact) or _BACK_EXACT.get(lower)
    if back:
        return back
    if compact.startswith("目录") or "tableofcontents" in lower.replace(" ", ""):
        return DocumentRole.TOC
    if compact.startswith("序") or compact.endswith("序"):
        return DocumentRole.PREFACE
    if _BODY_HEADING.match(compact) or _BODY_HEADING.match(heading):
        return DocumentRole.BODYMATTER
    return DocumentRole.OTHER


def role_family(role: DocumentRole) -> str:
    return ROLE_FAMILY.get(role, "other")


def role_families_differ(left: DocumentRole, right: DocumentRole) -> bool:
    return role_family(left) != role_family(right)


class StructureRoleHint(BaseModel):
    title: str
    role: DocumentRole

    @field_validator("role", mode="before")
    @classmethod
    def _coerce_role(cls, value: object) -> DocumentRole:
        if isinstance(value, DocumentRole):
            return value
        return parse_role(str(value) if value is not None else None)
