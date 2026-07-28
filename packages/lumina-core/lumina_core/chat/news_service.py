"""News article deep chat."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from lumina_core.db.repos import NewsChatRepo
from lumina_core.models.router import ProfileModelRouter, parse_json_response
from lumina_core.search.web import assess_evidence_sufficiency, search_web

NEWS_CHAT_SYSTEM = """你是 Lumina 资讯阅读助手。基于提供的文章信息回答问题。
- 文章事实必须基于给定标题与摘要
- 联网信息标注 [网]
- 无法从文章或联网确认时，明确拒答
输出 JSON：{"answer": "...", "citations": [], "web_refs": [{"title": "...", "url": "..."}], "evidence_sufficient": true}
"""


def build_article_context(article: dict[str, Any]) -> str:
    parts = [
        f"# {article.get('title', 'Article')}",
        f"来源: {article.get('url', '')}",
    ]
    if article.get("author"):
        parts.append(f"作者: {article['author']}")
    if article.get("published_at"):
        parts.append(f"发布时间: {article['published_at']}")
    if article.get("excerpt"):
        parts.append(f"\n## 摘要\n{article['excerpt']}")
    return "\n".join(parts)


async def prepare_news_chat(
    *,
    article: dict[str, Any],
    message: str,
    web_enabled: bool = True,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    context = build_article_context(article)
    web_refs: list[dict[str, str]] = []

    if web_enabled and not assess_evidence_sufficiency(message, context):
        results = await search_web(message)
        web_refs = [{"title": r.title, "url": r.url, "source": r.source} for r in results]
        if web_refs:
            context += "\n\n## 联网检索\n" + json.dumps(web_refs, ensure_ascii=False)

    messages: list[dict[str, str]] = [{"role": "system", "content": NEWS_CHAT_SYSTEM}]
    messages.append(
        {
            "role": "user",
            "content": f"文章:\n{context}\n\n用户问题: {message}",
        }
    )
    return messages, web_refs


async def chat_with_article(
    router: ProfileModelRouter,
    chat_repo: NewsChatRepo,
    *,
    article: dict[str, Any],
    message: str,
    web_enabled: bool = True,
) -> dict[str, Any]:
    history = chat_repo.list_messages(article["id"])[-6:]
    base_messages, web_refs = await prepare_news_chat(
        article=article,
        message=message,
        web_enabled=web_enabled,
    )
    messages = [base_messages[0]]
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append(base_messages[1])

    chat_repo.add_message(article["id"], "user", message)
    raw = await router.chat(messages, profile="chat", json_mode=True)
    assert isinstance(raw, str)
    parsed = parse_json_response(raw)
    answer = parsed.get("answer", raw)
    web_from_llm = parsed.get("web_refs", web_refs)

    chat_repo.add_message(
        article["id"],
        "assistant",
        answer,
        web_refs_json=json.dumps(web_from_llm, ensure_ascii=False),
    )
    return {
        "answer": answer,
        "citations": [],
        "web_refs": web_from_llm,
        "evidence_sufficient": parsed.get("evidence_sufficient", True),
    }


async def stream_chat_with_article(
    router: ProfileModelRouter,
    chat_repo: NewsChatRepo,
    *,
    article: dict[str, Any],
    message: str,
    web_enabled: bool = True,
) -> AsyncIterator[dict[str, Any]]:
    history = chat_repo.list_messages(article["id"])[-6:]
    base_messages, web_refs = await prepare_news_chat(
        article=article,
        message=message,
        web_enabled=web_enabled,
    )
    messages = [base_messages[0]]
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append(base_messages[1])

    chat_repo.add_message(article["id"], "user", message)

    stream = await router.chat(messages, profile="chat", stream=True, json_mode=True)
    assert not isinstance(stream, str)

    buffer = ""
    async for chunk in stream:
        buffer += chunk
        yield {"type": "token", "content": chunk}

    parsed = parse_json_response(buffer)
    answer = parsed.get("answer", buffer)
    web_from_llm = parsed.get("web_refs", web_refs)

    chat_repo.add_message(
        article["id"],
        "assistant",
        answer,
        web_refs_json=json.dumps(web_from_llm, ensure_ascii=False),
    )
    yield {
        "type": "done",
        "answer": answer,
        "citations": [],
        "web_refs": web_from_llm,
        "evidence_sufficient": parsed.get("evidence_sufficient", True),
    }
