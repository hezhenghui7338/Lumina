"""Deep chat with hierarchical index + DCA."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from lumina_core.db.repos import ChatRepo, SegmentRepo
from lumina_core.summarize.schema import format_summary_text, parse_segment_summary
from lumina_core.models.router import ProfileModelRouter, parse_chat_response
from lumina_core.search.web import assess_evidence_sufficiency, search_web

CHAT_SYSTEM = """你是 Lumina 阅读助手。基于提供的书籍上下文回答问题。
- 书中事实必须引用 [段 N]
- 联网信息标注 [网]
- 书中未提及且无法从联网确认时，明确拒答
输出 JSON：{"answer": "...", "citations": [{"segment_index": 0, "label": "[段 1]"}], "web_refs": [{"title": "...", "url": "..."}], "evidence_sufficient": true}
"""


def build_dca_context(
    book: dict[str, Any],
    segments: list[dict[str, Any]],
    current_idx: int,
    *,
    max_segments: int = 3,
) -> str:
    """Hierarchical Index + Dynamic Context Assembly."""
    lines = [
        f"# {book.get('title', 'Book')}",
        "## L0 书级",
        f"总段数: {book.get('segment_count', len(segments))}",
    ]

    lines.append("## L1 段摘要导航")
    for seg in segments[:50]:
        label = seg.get("label") or f"段 {seg['idx'] + 1}"
        status = seg.get("summary_status", "pending")
        lines.append(f"- [段 {seg['idx'] + 1}] {label} ({status})")

    lines.append("## L2 当前段原文")
    current = next((s for s in segments if s["idx"] == current_idx), None)
    if current:
        lines.append(current.get("raw_text", "")[:3000])
        if current.get("summary_json"):
            try:
                summary = parse_segment_summary(current["summary_json"])
                lines.append(format_summary_text(summary))
            except (json.JSONDecodeError, TypeError, ValueError):
                lines.append(f"摘要: {current['summary_json']}")

    nearby = sorted(segments, key=lambda s: abs(s["idx"] - current_idx))[:max_segments]
    lines.append("## L2 相关段摘录")
    for seg in nearby:
        if seg["idx"] == current_idx:
            continue
        excerpt = (seg.get("raw_text") or "")[:400]
        lines.append(f"### 段 {seg['idx'] + 1}\n{excerpt}")

    return "\n\n".join(lines)


async def prepare_chat(
    segment_repo: SegmentRepo,
    *,
    book: dict[str, Any],
    message: str,
    current_segment_idx: int = 0,
    quote: str | None = None,
    web_search_provider: str = "ddgs",
    tavily_api_key: str | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]], str]:
    segments = segment_repo.list_for_book(book["id"])
    context = build_dca_context(book, segments, current_segment_idx)
    web_refs: list[dict[str, str]] = []

    if not assess_evidence_sufficiency(message, context):
        results = await search_web(
            message,
            provider=web_search_provider,
            tavily_api_key=tavily_api_key,
        )
        web_refs = [{"title": r.title, "url": r.url, "source": r.source} for r in results]
        if web_refs:
            context += "\n\n## 联网检索\n" + json.dumps(web_refs, ensure_ascii=False)

    user_question = message
    if quote and quote.strip():
        user_question = f"用户选中的原文:\n「{quote.strip()}」\n\n问题: {message}"

    messages: list[dict[str, str]] = [{"role": "system", "content": CHAT_SYSTEM}]
    messages.append(
        {
            "role": "user",
            "content": f"上下文:\n{context}\n\n用户问题: {user_question}",
        }
    )
    return messages, web_refs, context


async def chat_with_book(
    router: ProfileModelRouter,
    chat_repo: ChatRepo,
    segment_repo: SegmentRepo,
    *,
    book: dict[str, Any],
    message: str,
    current_segment_idx: int = 0,
    quote: str | None = None,
    web_search_provider: str = "ddgs",
    tavily_api_key: str | None = None,
) -> dict[str, Any]:
    session = chat_repo.get_or_create_session(book["id"])
    history = chat_repo.list_messages(session["id"])[-6:]

    base_messages, web_refs, _ = await prepare_chat(
        segment_repo,
        book=book,
        message=message,
        current_segment_idx=current_segment_idx,
        quote=quote,
        web_search_provider=web_search_provider,
        tavily_api_key=tavily_api_key,
    )
    messages = [base_messages[0]]
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append(base_messages[1])

    chat_repo.add_message(session["id"], "user", message)
    raw = await router.chat(messages, profile="chat", json_mode=True)
    assert isinstance(raw, str)
    parsed = parse_chat_response(raw)
    answer = parsed.get("answer", raw)
    citations = parsed.get("citations", [])
    web_from_llm = parsed.get("web_refs", web_refs)

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
    web_search_provider: str = "ddgs",
    tavily_api_key: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    try:
        session = chat_repo.get_or_create_session(book["id"])
        history = chat_repo.list_messages(session["id"])[-6:]

        base_messages, web_refs, _ = await prepare_chat(
            segment_repo,
            book=book,
            message=message,
            current_segment_idx=current_segment_idx,
            quote=quote,
            web_search_provider=web_search_provider,
            tavily_api_key=tavily_api_key,
        )
        messages = [base_messages[0]]
        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append(base_messages[1])

        chat_repo.add_message(session["id"], "user", message)

        stream = await router.chat(messages, profile="chat", stream=True, json_mode=True)
        assert not isinstance(stream, str)

        buffer = ""
        async for chunk in stream:
            buffer += chunk
            yield {"type": "token", "content": chunk}

        parsed = parse_chat_response(buffer)
        answer = parsed.get("answer", buffer)
        citations = parsed.get("citations", [])
        web_from_llm = parsed.get("web_refs", web_refs)

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
        }
    except Exception as exc:
        yield {
            "type": "error",
            "message": f"深聊失败：{exc}",
        }
