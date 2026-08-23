"""Deep chat with hierarchical index + DCA."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Any, Literal

from lumina_core.config import (
    CHAT_CONTEXT_MAX_CHARS,
    PromptsConfig,
    load_prompts_config,
)
from lumina_core.db.repos import ChatRepo, NoteRepo, SegmentRepo, SummaryNodeRepo
from lumina_core.models.router import ProfileModelRouter, parse_chat_response
from lumina_core.search.evidence import (
    WEB_EVIDENCE_RESERVE_CHARS,
    prepare_web_evidence,
    will_use_web,
)
from lumina_core.search.fts import search_book_segments
from lumina_core.summarize.rollup import summary_plain_text
from lumina_core.summarize.schema import format_summary_text, parse_segment_summary

ChatScope = Literal["segment", "book"]

CURRENT_ORIGINAL_CHARS = 3000
NEARBY_ORIGINAL_CHARS = 400
MAX_NEARBY = 3
MAX_HIT_SEGMENTS = 6
MAX_RELATED_FTS = 3
NOTES_MAX_CHARS = 600
HISTORY_LIMIT = 20
DOC_CONTEXT_MAX_CHARS = max(2000, CHAT_CONTEXT_MAX_CHARS - WEB_EVIDENCE_RESERVE_CHARS)
WEB_STATUS_MESSAGE = "正在检索网络…"


class ContextBudget:
    def __init__(self, max_chars: int = CHAT_CONTEXT_MAX_CHARS) -> None:
        self.max_chars = max_chars
        self.used = 0
        self.parts: list[str] = []

    def add(self, text: str) -> bool:
        if not text or self.used >= self.max_chars:
            return False
        remaining = self.max_chars - self.used
        chunk = text if len(text) <= remaining else text[:remaining].rstrip()
        self.parts.append(chunk)
        self.used += len(chunk) + 2
        return len(text) <= remaining

    def render(self) -> str:
        return "\n\n".join(self.parts)


def _format_stored_summary(summary_json: Any) -> str:
    if not summary_json:
        return ""
    try:
        summary = parse_segment_summary(summary_json)
        return format_summary_text(summary)
    except (json.JSONDecodeError, TypeError, ValueError):
        if isinstance(summary_json, str):
            return summary_json
        return json.dumps(summary_json, ensure_ascii=False)


def _node_body(node: dict[str, Any]) -> str:
    formatted = _format_stored_summary(node.get("summary_json"))
    if formatted:
        return formatted
    return summary_plain_text(node.get("summary_json"), label=str(node.get("label") or ""))


def _range_heading(node: dict[str, Any]) -> str:
    start = node.get("segment_idx_start")
    end = node.get("segment_idx_end")
    label = node.get("label") or ""
    if start is None:
        return label or "摘要"
    start_n = int(start) + 1
    end_n = int(end) + 1 if end is not None else start_n
    span = f"段 {start_n}" if start_n == end_n else f"段 {start_n}–{end_n}"
    return f"{span} · {label}" if label else span


def _book_heading(book: dict[str, Any]) -> str:
    title = str(book.get("title") or "Book").strip() or "Book"
    author = str(book.get("author") or "").strip()
    return f"# {title} · {author}" if author else f"# {title}"


def _fts_query(message: str, label: str | None) -> str:
    """Build an FTS MATCH string; space-separated terms are OR'd so extra words don't hide hits."""
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in ((message or "").strip(), (label or "").strip()):
        if not raw:
            continue
        cleaned = re.sub(r'["\'*^:(){}[\]]', " ", raw)
        for token in cleaned.split():
            if token.upper() == "OR" or token in seen:
                continue
            seen.add(token)
            tokens.append(token)
    if not tokens:
        return ""
    if len(tokens) == 1:
        return tokens[0]
    return " OR ".join(tokens)


def _format_notes(notes: list[dict[str, Any]], *, max_chars: int = NOTES_MAX_CHARS) -> str:
    parts: list[str] = []
    used = 0
    for note in notes:
        content = (note.get("content") or "").strip()
        quote = (note.get("quote") or "").strip()
        if quote and content:
            item = f"- 「{quote}」{content}"
        elif quote:
            item = f"- 「{quote}」"
        elif content:
            item = f"- {content}"
        else:
            continue
        if used + len(item) > max_chars:
            remain = max_chars - used
            if remain > 8:
                parts.append(item[:remain].rstrip())
            break
        parts.append(item)
        used += len(item) + 1
    return "\n".join(parts)


def build_dca_context(
    book: dict[str, Any],
    segments: list[dict[str, Any]],
    current_idx: int,
    *,
    max_segments: int = MAX_NEARBY,
    root_text: str | None = None,
    related_excerpts: list[tuple[int, str]] | None = None,
    notes_text: str | None = None,
    max_chars: int | None = None,
) -> str:
    """Segment-scope DCA. `segments` should be current + nearby."""
    budget = ContextBudget(max_chars if max_chars is not None else DOC_CONTEXT_MAX_CHARS)
    budget.add(_book_heading(book))
    if root_text:
        budget.add("## L0 全书总摘要")
        budget.add(root_text)
    current = next((s for s in segments if s.get("idx") == current_idx), None)
    if current:
        budget.add("## L2 当前段原文")
        budget.add((current.get("raw_text") or "")[:CURRENT_ORIGINAL_CHARS])
        formatted = _format_stored_summary(current.get("summary_json"))
        if formatted:
            budget.add(formatted)
    if notes_text:
        budget.add("## 用户笔记")
        budget.add(notes_text)
    nearby = sorted(segments, key=lambda s: abs(int(s.get("idx", 0)) - current_idx))[
        :max_segments
    ]
    extras = [seg for seg in nearby if seg.get("idx") != current_idx]
    if extras:
        budget.add("## L2 相关段摘录")
        for seg in extras:
            excerpt = (seg.get("raw_text") or "")[:NEARBY_ORIGINAL_CHARS]
            budget.add(f"### 段 {int(seg['idx']) + 1}\n{excerpt}")
    if related_excerpts:
        budget.add("## L2 书内相关段")
        for idx, excerpt in related_excerpts:
            budget.add(f"### 段 {idx + 1}\n{excerpt}")
    return budget.render()


def build_book_dca_context(
    book: dict[str, Any],
    *,
    root_text: str,
    cluster_nodes: list[dict[str, Any]],
    segment_summaries: list[tuple[int, str, str]],
    originals: list[tuple[int, str]],
    max_chars: int | None = None,
) -> str:
    """Assemble book-scope context in 总摘要 → 分摘要 → 原文 order."""
    budget = ContextBudget(max_chars if max_chars is not None else DOC_CONTEXT_MAX_CHARS)
    budget.add(_book_heading(book))
    budget.add("## L0 全书总摘要")
    budget.add(root_text)
    if cluster_nodes:
        budget.add("## L1 分摘要")
        for node in cluster_nodes:
            body = _node_body(node)
            if not body:
                continue
            budget.add(f"### {_range_heading(node)}\n{body}")
    if segment_summaries:
        budget.add("## L1 相关段摘要")
        for idx, label, body in segment_summaries:
            heading = label or f"段 {idx + 1}"
            budget.add(f"### 段 {idx + 1} · {heading}\n{body}")
    if originals:
        budget.add("## L2 原文证据")
        for idx, text in originals:
            budget.add(f"### 段 {idx + 1}\n{text}")
    return budget.render()


def assemble_book_context(
    conn,
    book: dict[str, Any],
    *,
    message: str,
    node_repo: SummaryNodeRepo,
    segment_repo: SegmentRepo,
    current_segment_idx: int | None = None,
) -> str:
    root = node_repo.get_root(book["id"])
    root_text = _node_body(root) if root else "（全书总摘要尚未生成）"
    nodes = node_repo.list_for_book(book["id"])
    label = ""
    if current_segment_idx is not None:
        current_body = segment_repo.get_bodies_by_indices(book["id"], [current_segment_idx]).get(
            current_segment_idx
        )
        label = str((current_body or {}).get("label") or "")
    hits = search_book_segments(
        conn, book["id"], _fts_query(message, label), limit=MAX_HIT_SEGMENTS
    )
    hit_indices = [
        int(h["segment_index"])
        for h in hits
        if h.get("segment_index") is not None
    ]
    ordered: list[int] = []
    for idx in hit_indices:
        if idx not in ordered:
            ordered.append(idx)
    ordered = ordered[:MAX_HIT_SEGMENTS]

    cluster_nodes = [
        n
        for n in nodes
        if n.get("segment_id") is None and int(n.get("level") or 0) > 0
    ]
    cluster_nodes.sort(key=lambda n: (int(n.get("level") or 0), int(n.get("sort_idx") or 0)))

    bodies = segment_repo.get_bodies_by_indices(book["id"], ordered) if ordered else {}
    segment_summaries: list[tuple[int, str, str]] = []
    originals: list[tuple[int, str]] = []
    for idx in ordered:
        row = bodies.get(idx)
        if not row:
            continue
        formatted = _format_stored_summary(row.get("summary_json"))
        if formatted:
            segment_summaries.append((idx, str(row.get("label") or ""), formatted))
        raw = row.get("raw_text") or ""
        cap = (
            CURRENT_ORIGINAL_CHARS
            if current_segment_idx is not None and idx == current_segment_idx
            else NEARBY_ORIGINAL_CHARS
        )
        if raw:
            originals.append((idx, raw[:cap]))
    return build_book_dca_context(
        book,
        root_text=root_text,
        cluster_nodes=cluster_nodes,
        segment_summaries=segment_summaries,
        originals=originals,
    )


def assemble_segment_context(
    book: dict[str, Any],
    *,
    current_segment_idx: int,
    segment_repo: SegmentRepo,
    node_repo: SummaryNodeRepo | None = None,
    message: str = "",
    note_repo: NoteRepo | None = None,
) -> str:
    nearby_idxs = [
        i
        for i in range(current_segment_idx - 1, current_segment_idx + 2)
        if i >= 0
    ]
    nearby_set = set(nearby_idxs)
    bodies = segment_repo.get_bodies_by_indices(book["id"], nearby_idxs)
    loaded = [bodies[i] for i in sorted(bodies)]
    current = bodies.get(current_segment_idx)
    label = str((current or {}).get("label") or "")

    related_excerpts: list[tuple[int, str]] = []
    query = _fts_query(message, label)
    if query:
        hits = search_book_segments(
            segment_repo.conn, book["id"], query, limit=MAX_RELATED_FTS + len(nearby_set)
        )
        related_idxs: list[int] = []
        for hit in hits:
            idx = hit.get("segment_index")
            if idx is None:
                continue
            idx = int(idx)
            if idx in nearby_set or idx in related_idxs:
                continue
            related_idxs.append(idx)
            if len(related_idxs) >= MAX_RELATED_FTS:
                break
        if related_idxs:
            related_bodies = segment_repo.get_bodies_by_indices(book["id"], related_idxs)
            for idx in related_idxs:
                row = related_bodies.get(idx)
                if not row:
                    continue
                excerpt = (row.get("raw_text") or "")[:NEARBY_ORIGINAL_CHARS]
                if excerpt:
                    related_excerpts.append((idx, excerpt))

    notes_text = None
    if note_repo is not None and current and current.get("id"):
        notes = note_repo.list_for_book(book["id"], segment_id=str(current["id"]))
        notes_text = _format_notes(notes) or None

    root_text = None
    if node_repo is not None:
        root = node_repo.get_root(book["id"])
        if root:
            root_text = _node_body(root)
    return build_dca_context(
        book,
        loaded,
        current_segment_idx,
        root_text=root_text,
        related_excerpts=related_excerpts or None,
        notes_text=notes_text,
    )


def _merge_web_block(context: str, block: str) -> str:
    if not block:
        return context
    return f"{context}\n\n{block}"


def _chat_messages(
    context: str,
    message: str,
    quote: str | None,
    prompts: PromptsConfig | None,
    *,
    scope: ChatScope = "segment",
) -> list[dict[str, str]]:
    from lumina_core.prompts_defaults import BOOK_SCOPE_CHAT_RULES

    user_question = message
    if quote and quote.strip():
        user_question = f"用户选中的原文:\n「{quote.strip()}」\n\n问题: {message}"
    chat_system = (prompts or load_prompts_config()).chat
    if scope == "book":
        chat_system = f"{chat_system.rstrip()}\n{BOOK_SCOPE_CHAT_RULES}"
    return [
        {"role": "system", "content": chat_system},
        {
            "role": "user",
            "content": f"上下文:\n{context}\n\n用户问题: {user_question}",
        },
    ]


async def assemble_chat_document(
    segment_repo: SegmentRepo,
    *,
    book: dict[str, Any],
    message: str,
    current_segment_idx: int = 0,
    scope: ChatScope = "segment",
    node_repo: SummaryNodeRepo | None = None,
    note_repo: NoteRepo | None = None,
    conn=None,
) -> str:
    resolved_nodes = node_repo or (
        SummaryNodeRepo(conn) if conn is not None else SummaryNodeRepo(segment_repo.conn)
    )
    resolved_notes = note_repo or NoteRepo(resolved_nodes.conn)
    if scope == "book":
        return await asyncio.to_thread(
            assemble_book_context,
            resolved_nodes.conn,
            book,
            message=message,
            current_segment_idx=current_segment_idx,
            node_repo=resolved_nodes,
            segment_repo=segment_repo,
        )
    return await asyncio.to_thread(
        assemble_segment_context,
        book,
        current_segment_idx=current_segment_idx,
        segment_repo=segment_repo,
        node_repo=resolved_nodes,
        message=message,
        note_repo=resolved_notes,
    )


async def prepare_chat(
    segment_repo: SegmentRepo,
    *,
    book: dict[str, Any],
    message: str,
    current_segment_idx: int = 0,
    quote: str | None = None,
    scope: ChatScope = "segment",
    web_search_provider: str = "ddgs",
    tavily_api_key: str | None = None,
    web_search_enabled: bool = True,
    prompts: PromptsConfig | None = None,
    node_repo: SummaryNodeRepo | None = None,
    note_repo: NoteRepo | None = None,
    conn=None,
) -> tuple[list[dict[str, str]], list[dict[str, str]], str]:
    context = await assemble_chat_document(
        segment_repo,
        book=book,
        message=message,
        current_segment_idx=current_segment_idx,
        scope=scope,
        node_repo=node_repo,
        note_repo=note_repo,
        conn=conn,
    )
    evidence = await prepare_web_evidence(
        message,
        context,
        enabled=web_search_enabled,
        provider=web_search_provider,
        tavily_api_key=tavily_api_key,
    )
    context = _merge_web_block(context, evidence.block)
    return _chat_messages(context, message, quote, prompts, scope=scope), evidence.refs, context


def _with_history(
    base_messages: list[dict[str, str]],
    history: list[dict[str, Any]],
) -> list[dict[str, str]]:
    messages = [base_messages[0]]
    for msg in history[-HISTORY_LIMIT:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append(base_messages[1])
    return messages


async def chat_with_book(
    router: ProfileModelRouter,
    chat_repo: ChatRepo,
    segment_repo: SegmentRepo,
    *,
    book: dict[str, Any],
    message: str,
    current_segment_idx: int = 0,
    quote: str | None = None,
    scope: ChatScope = "segment",
    web_search_provider: str = "ddgs",
    tavily_api_key: str | None = None,
    web_search_enabled: bool = True,
    prompts: PromptsConfig | None = None,
    node_repo: SummaryNodeRepo | None = None,
    note_repo: NoteRepo | None = None,
) -> dict[str, Any]:
    session = chat_repo.get_or_create_session(book["id"])
    history = chat_repo.list_messages(session["id"])[-HISTORY_LIMIT:]

    base_messages, web_refs, _ = await prepare_chat(
        segment_repo,
        book=book,
        message=message,
        current_segment_idx=current_segment_idx,
        quote=quote,
        scope=scope,
        web_search_provider=web_search_provider,
        tavily_api_key=tavily_api_key,
        web_search_enabled=web_search_enabled,
        prompts=prompts,
        node_repo=node_repo,
        note_repo=note_repo,
    )
    messages = _with_history(base_messages, history)

    chat_repo.add_message(session["id"], "user", message)
    raw = await router.chat(messages, profile="chat", json_mode=True)
    assert isinstance(raw, str)
    parsed = parse_chat_response(raw)
    answer = parsed.get("answer", raw)
    citations = parsed.get("citations", [])
    web_from_llm = parsed.get("web_refs") or web_refs

    chat_repo.add_message(
        session["id"],
        "assistant",
        answer,
        citations_json=json.dumps(citations, ensure_ascii=False),
        web_refs_json=json.dumps(web_from_llm, ensure_ascii=False),
    )
    return {
        "answer": answer,
        "citations": citations,
        "web_refs": web_from_llm,
        "evidence_sufficient": parsed.get("evidence_sufficient", True),
        "session_id": session["id"],
        **router.chat_metrics(),
    }


async def stream_chat_with_book(
    router: ProfileModelRouter,
    chat_repo: ChatRepo,
    segment_repo: SegmentRepo,
    *,
    book: dict[str, Any],
    message: str,
    current_segment_idx: int = 0,
    quote: str | None = None,
    scope: ChatScope = "segment",
    web_search_provider: str = "ddgs",
    tavily_api_key: str | None = None,
    web_search_enabled: bool = True,
    prompts: PromptsConfig | None = None,
    node_repo: SummaryNodeRepo | None = None,
    note_repo: NoteRepo | None = None,
) -> AsyncIterator[dict[str, Any]]:
    try:
        session = chat_repo.get_or_create_session(book["id"])
        history = chat_repo.list_messages(session["id"])[-HISTORY_LIMIT:]

        context = await assemble_chat_document(
            segment_repo,
            book=book,
            message=message,
            current_segment_idx=current_segment_idx,
            scope=scope,
            node_repo=node_repo,
            note_repo=note_repo,
        )
        if will_use_web(
            message,
            context,
            enabled=web_search_enabled,
            provider=web_search_provider,
        ):
            yield {"type": "status", "message": WEB_STATUS_MESSAGE}
        evidence = await prepare_web_evidence(
            message,
            context,
            enabled=web_search_enabled,
            provider=web_search_provider,
            tavily_api_key=tavily_api_key,
        )
        context = _merge_web_block(context, evidence.block)
        web_refs = evidence.refs
        base_messages = _chat_messages(context, message, quote, prompts, scope=scope)
        messages = _with_history(base_messages, history)

        chat_repo.add_message(session["id"], "user", message)

        stream = await router.chat(messages, profile="chat", json_mode=True, stream=True)
        assert not isinstance(stream, str)

        buffer = ""
        async for chunk in stream:
            buffer += chunk
            yield {"type": "token", "content": chunk}

        parsed = parse_chat_response(buffer)
        answer = parsed.get("answer", buffer)
        citations = parsed.get("citations", [])
        web_from_llm = parsed.get("web_refs") or web_refs

        chat_repo.add_message(
            session["id"],
            "assistant",
            answer,
            citations_json=json.dumps(citations, ensure_ascii=False),
            web_refs_json=json.dumps(web_from_llm, ensure_ascii=False),
        )
        yield {
            "type": "done",
            "answer": answer,
            "citations": citations,
            "web_refs": web_from_llm,
            "evidence_sufficient": parsed.get("evidence_sufficient", True),
            "session_id": session["id"],
            **router.chat_metrics(),
        }
    except Exception as exc:
        yield {
            "type": "error",
            "message": f"深聊失败：{exc}",
        }
