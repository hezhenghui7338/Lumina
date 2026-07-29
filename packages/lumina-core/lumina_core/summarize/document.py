"""One-click document summarize — short-path card for news deep-read."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lumina_core.chunker.chunker import chunk_text
from lumina_core.config import (
    MAX_SUMMARY_RETRIES,
    SUMMARIZE_LLM_INPUT_CHARS,
    SUMMARIZE_SHORT_MAX_CHARS,
    resolve_chunk_budget,
)
from lumina_core.models.router import ProfileModelRouter
from lumina_core.summarize.segment import summarize_segment

_CITE_RE = re.compile(
    r"〔[^〕]+〕"
    r"|\[p\.\d+\]"
    r"|〔?§[^\s，,;；|〕\]]+"
    r"|Sheet\s*[:：]?\s*\S+"
    r"|p\.\d+",
    re.IGNORECASE,
)
_BULLET_RE = re.compile(r"^\s*[-*•]\s+")
_HEADING_SUM = re.compile(r"^##\s*总结")
_HEADING_POINTS = re.compile(r"^##\s*结构化要点")
_HEADING_ASK = re.compile(r"^##\s*你可以接着问")
_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+)$")


@dataclass
class DocSection:
    heading: str
    text: str


@dataclass
class DocumentSummarizeResult:
    markdown: str
    warnings: list[str] = field(default_factory=list)
    used_llm: bool = False
    segment_mode: bool = False


def _detect_heading(line: str) -> tuple[int, str] | None:
    m = _MD_HEADING.match((line or "").strip())
    if not m:
        return None
    return len(m.group(1)), m.group(2).strip()


def split_into_sections(content: str, *, filename: str = "article") -> list[DocSection]:
    lines = (content or "").splitlines()
    if not lines:
        return []
    raw: list[dict] = []
    current: dict | None = None
    for idx, line in enumerate(lines):
        heading = _detect_heading(line)
        if heading:
            if current is not None:
                current["content"] = "\n".join(lines[current["_start"] : idx])
                raw.append(current)
            current = {
                "heading": line.rstrip(),
                "_start": idx,
            }
    if current is not None:
        current["content"] = "\n".join(lines[current["_start"] :])
        raw.append(current)
    if not raw:
        return [DocSection(heading="(全文)", text=content)]
    sections: list[DocSection] = []
    for section in raw:
        sections.append(
            DocSection(heading=section["heading"], text=section.get("content") or "")
        )
    return sections


def annotate_for_cite(text: str, *, filename: str = "article") -> str:
    sections = split_into_sections(text, filename=filename)
    parts: list[str] = []
    for section in sections:
        title = section.heading.lstrip("# ").strip() or "全文"
        marker = f"[§{title}]"
        body = section.text.strip()
        if body.startswith(section.heading):
            body = "\n".join(body.splitlines()[1:]).strip()
        parts.append(f"{marker}\n{body}" if body else marker)
    return "\n\n".join(parts)


def _prompt(annotated: str, *, filename: str) -> str:
    return (
        "你是文档速读助手。根据下列带索引标记的原文，输出「3 分钟读懂」卡片。\n"
        "硬性规则：\n"
        "1. 「总结」用 1～最多 3 句话；能一句说清就一句，禁止凑满三条或注水。\n"
        "2. 「结构化要点」5～8 条；每条必须带具体索引，格式强制为 "
        "〔§章节 | p.页〕或 〔§章节〕或 〔p.页〕。\n"
        "3. 索引必须来自原文中的 [§…] / [p.…] 标记，禁止编造页码或章节。\n"
        "4. 找不到依据的要点宁可省略，也不要瞎写索引。\n"
        "5. 「需要注意」仅在有局限/免责/反方观点时写；否则整节省略。\n"
        "6. 「你可以接着问」给 2～3 个短问题，且必须是原文已覆盖、可继续追问的点；"
        "原文只有导语/摘要时请整节省略该段，禁止编造机制/架构细节类问题。\n"
        "7. 只输出 Markdown，不要前言后语。\n\n"
        "输出模板：\n"
        "## 总结（最多三句话）\n"
        "…\n\n"
        "## 结构化要点\n"
        "- **要点**：… — 依据：… 〔§… | p.…〕\n\n"
        "## 需要注意\n"
        "- …\n\n"
        "## 你可以接着问\n"
        "1. …\n\n"
        f"文件名: {filename}\n\n"
        f"原文（含索引标记）:\n{annotated}"
    )


def _strip_marker_noise(text: str) -> str:
    cleaned = re.sub(r"(?m)^#{1,6}\s*", "", text or "")
    cleaned = re.sub(r"\[§[^\]]+\]|\[p\.\d+\]", "", cleaned)
    return " ".join(cleaned.split()).strip()


def _cite_from_heading(heading: str) -> str:
    title = (heading or "").lstrip("# ").strip() or "全文"
    if title.startswith("[") and title.endswith("]"):
        inner = title[1:-1]
        return inner if inner.startswith(("§", "p.")) else f"§{inner}"
    if title.startswith(("§", "p.")):
        return title
    return f"§{title}"


def heuristic_summary(annotated: str, *, filename: str = "article") -> str:
    sections = split_into_sections(annotated, filename=filename)
    prose = _strip_marker_noise(annotated)
    sentences = [
        s.strip()
        for s in re.split(r"(?<=[。！？.!?])\s+", prose)
        if s.strip() and len(s.strip()) > 8
    ]
    lead = sentences[0] if sentences else f"文档 {filename} 的要点如下。"
    if len(lead) > 160:
        lead = lead[:159] + "…"
    lines = ["## 总结（最多三句话）", lead, "", "## 结构化要点"]
    count = 0
    for section in sections:
        if count >= 6:
            break
        cite = _cite_from_heading(section.heading)
        body = _strip_marker_noise(section.text)
        title_plain = cite.lstrip("§").lstrip("p.").strip()
        if body.startswith(title_plain):
            body = body[len(title_plain) :].lstrip(" ：:>-").strip()
        if not body:
            continue
        snippet = body[:120] + ("…" if len(body) > 120 else "")
        label = title_plain or cite
        lines.append(f"- **{label}**：{snippet} — 依据：原文 〔{cite}〕")
        count += 1
    if count == 0:
        lines.append(f"- **全文**：{lead} — 依据：原文 〔§全文〕")
    lines.extend(["", "## 你可以接着问", "1. 哪一节最值得展开？", "2. 有哪些需要注意的限制？"])
    return "\n".join(lines)


def _strip_fence(text: str) -> str:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:markdown|md)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def citation_ok(line: str) -> bool:
    return bool(_CITE_RE.search(line))


def ensure_citations(markdown: str) -> tuple[str, list[str]]:
    warnings: list[str] = []
    lines = markdown.splitlines()
    out: list[str] = []
    in_points = False
    fixed = 0
    for line in lines:
        if _HEADING_POINTS.match(line):
            in_points = True
            out.append(line)
            continue
        if line.startswith("## "):
            in_points = False
            out.append(line)
            continue
        if in_points and _BULLET_RE.match(line) and not citation_ok(line):
            out.append(line.rstrip() + " 〔未定位到页/节〕")
            fixed += 1
            continue
        out.append(line)
    if fixed:
        warnings.append(f"{fixed} 条要点缺少可核对索引，已标注「未定位到页/节」")
    return "\n".join(out).strip() + "\n", warnings


def omit_misleading_asks(markdown: str, *, body_complete: bool) -> str:
    if body_complete or not markdown:
        return markdown
    lines = markdown.splitlines()
    out: list[str] = []
    skipping = False
    for line in lines:
        if _HEADING_ASK.match(line):
            skipping = True
            continue
        if skipping and line.startswith("## "):
            skipping = False
        if skipping:
            continue
        out.append(line)
    return "\n".join(out).rstrip() + "\n"


def _segment_summaries_to_card(parts: list[tuple[str, list[str], list[str]]]) -> str:
    """Build a markdown card from segment summaries: (label, sentences, bullets)."""
    lead_sents: list[str] = []
    bullets: list[str] = []
    for label, sentences, segs_bullets in parts:
        lead_sents.extend(sentences[:1])
        for b in segs_bullets[:3]:
            bullets.append(f"- **{label}**：{b} — 依据：原文 〔§{label}〕")
    lead = " ".join(lead_sents[:3]) or "本文按段落摘要如下。"
    lines = ["## 总结（最多三句话）", lead, "", "## 结构化要点"]
    lines.extend(bullets[:8] or [f"- **全文**：{lead} — 依据：原文 〔§全文〕"])
    lines.extend(["", "## 你可以接着问", "1. 哪一段最值得展开？", "2. 有哪些需要注意的限制？"])
    return "\n".join(lines)


async def summarize_document(
    router: ProfileModelRouter,
    *,
    text: str,
    title: str = "article",
    use_llm: bool = True,
    allow_long: bool = True,
) -> DocumentSummarizeResult:
    """Produce a short-path markdown card; long docs fall back to segment summarize."""
    warnings: list[str] = []
    body = (text or "").strip()
    if not body:
        return DocumentSummarizeResult(markdown="", warnings=["空正文"])

    annotated = annotate_for_cite(body, filename=title)
    char_count = len(annotated)

    if char_count > SUMMARIZE_SHORT_MAX_CHARS and allow_long:
        warnings.append(f"正文过长（约 {char_count} 字），已按分段摘要生成速读卡")
        chunks = chunk_text(body, budget=resolve_chunk_budget(router.models))
        parts: list[tuple[str, list[str], list[str]]] = []
        # Cap to first few segments for latency.
        for chunk in chunks[:6]:
            label = chunk.chapter or f"段 {chunk.index + 1}"
            if use_llm:
                try:
                    result = await summarize_segment(
                        router, raw_text=chunk.raw_text, anchor_label=label
                    )
                    summary = result.summary
                    parts.append(
                        (
                            summary.label or label,
                            list(summary.sentences),
                            [f"{b.label}：{b.body}" if b.label else b.body for b in summary.bullets],
                        )
                    )
                    continue
                except Exception as exc:
                    warnings.append(f"段摘要失败({label}): {exc}")
            # Heuristic per segment
            sent = _strip_marker_noise(chunk.raw_text)[:120]
            parts.append((label, [sent], [sent]))
        card = _segment_summaries_to_card(parts)
        card, cite_warns = ensure_citations(card)
        warnings.extend(cite_warns)
        return DocumentSummarizeResult(
            markdown=card, warnings=warnings, used_llm=use_llm, segment_mode=True
        )

    if char_count > SUMMARIZE_SHORT_MAX_CHARS and not allow_long:
        annotated = annotated[: SUMMARIZE_SHORT_MAX_CHARS - 1] + "…"
        warnings.append(f"正文过长（约 {char_count} 字），速读卡按截断文本生成")

    markdown = ""
    used_llm = False
    if use_llm:
        clipped = annotated[:SUMMARIZE_LLM_INPUT_CHARS]
        prompt = _prompt(clipped, filename=title)
        for _ in range(MAX_SUMMARY_RETRIES):
            try:
                raw = await router.complete(prompt, profile="summarize", json_mode=False)
                text_out = _strip_fence(raw)
                if text_out and "##" in text_out:
                    markdown = text_out
                    used_llm = True
                    break
            except Exception as exc:
                warnings.append(f"LLM 摘要失败: {exc}")

    if not markdown:
        markdown = heuristic_summary(annotated, filename=title)
        if use_llm:
            warnings.append("模型摘要不可用，已使用本地启发式摘要")

    markdown, cite_warns = ensure_citations(markdown)
    warnings.extend(cite_warns)
    return DocumentSummarizeResult(
        markdown=markdown, warnings=warnings, used_llm=used_llm, segment_mode=False
    )
