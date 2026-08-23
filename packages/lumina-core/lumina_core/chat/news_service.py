"""News article deep chat."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from lumina_core.chat.service import HISTORY_LIMIT, WEB_STATUS_MESSAGE
from lumina_core.config import PromptsConfig, load_prompts_config
from lumina_core.db.repos import NewsChatRepo
from lumina_core.models.router import ProfileModelRouter, parse_chat_response
from lumina_core.news.read import load_cached_body
from lumina_core.news.summary_parse import parse_rss_summary
from lumina_core.search.evidence import prepare_web_evidence, will_use_web

NEWS_BODY_CHARS = 12000


def build_article_context(article: dict[str, Any]) -> str:
    parts = [
        f"# {article.get('title', 'Article')}",
        f"来源: {article.get('url', '')}",
    ]
    if article.get("author"):
        parts.append(f"作者: {article['author']}")
    if article.get("published_at"):
        parts.append(f"发布时间: {article['published_at']}")

    body = load_cached_body(article)
    if body:
        parts.append(f"\n## 正文\n{body[:NEWS_BODY_CHARS]}")
        return "\n".join(parts)

    parsed = parse_rss_summary(article.get("rss_summary") or "")
    if parsed.one_liner or parsed.detail or parsed.viewpoints:
        parts.append("\n## RSS 结构化摘要")
        if parsed.one_liner:
            parts.append(parsed.one_liner)
        if parsed.detail:
            parts.append(parsed.detail)
        if parsed.viewpoints:
            parts.append("主要观点：\n" + "\n".join(f"- {v}" for v in parsed.viewpoints))
        return "\n".join(parts)

    if article.get("summary_markdown"):
        parts.append(f"\n## 速读卡\n{article['summary_markdown']}")
    if article.get("excerpt"):
        parts.append(f"\n## 摘要\n{article['excerpt']}")
    return "\n".join(parts)


def _news_messages(
    context: str,
    message: str,
    quote: str | None,
    prompts: PromptsConfig | None,
) -> list[dict[str, str]]:
    if quote and quote.strip():
        user_question = f"用户选中的原文:\n「{quote.strip()}」\n\n问题: {message}"
    else:
        user_question = f"用户问题: {message}"
    news_chat_system = (prompts or load_prompts_config()).news_chat
    return [
        {"role": "system", "content": news_chat_system},
        {
            "role": "user",
            "content": f"文章:\n{context}\n\n{user_question}",
        },
    ]


def _with_history(
    base_messages: list[dict[str, str]],
    history: list[dict[str, Any]],
) -> list[dict[str, str]]:
    messages = [base_messages[0]]
    for msg in history[-HISTORY_LIMIT:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append(base_messages[1])
    return messages


async def prepare_news_chat(
    *,
    article: dict[str, Any],
    message: str,
    quote: str | None = None,
    web_search_provider: str = "ddgs",
    tavily_api_key: str | None = None,
    web_search_enabled: bool = True,
    prompts: PromptsConfig | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    context = build_article_context(article)
    evidence = await prepare_web_evidence(
        message,
        context,
        enabled=web_search_enabled,
        provider=web_search_provider,
        tavily_api_key=tavily_api_key,
    )
    if evidence.block:
        context = f"{context}\n\n{evidence.block}"
    return _news_messages(context, message, quote, prompts), evidence.refs


async def chat_with_article(
    router: ProfileModelRouter,
    chat_repo: NewsChatRepo,
    *,
    article: dict[str, Any],
    message: str,
    quote: str | None = None,
    web_search_provider: str = "ddgs",
    tavily_api_key: str | None = None,
    web_search_enabled: bool = True,
    prompts: PromptsConfig | None = None,
) -> dict[str, Any]:
    history = chat_repo.list_messages(article["id"])[-HISTORY_LIMIT:]
    base_messages, web_refs = await prepare_news_chat(
        article=article,
        message=message,
        quote=quote,
        web_search_provider=web_search_provider,
        tavily_api_key=tavily_api_key,
        web_search_enabled=web_search_enabled,
        prompts=prompts,
    )
    messages = _with_history(base_messages, history)

    chat_repo.add_message(article["id"], "user", message)
    raw = await router.chat(messages, profile="chat", json_mode=True)
    assert isinstance(raw, str)
    parsed = parse_chat_response(raw)
    answer = parsed.get("answer", raw)
    web_from_llm = parsed.get("web_refs") or web_refs

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
        **router.chat_metrics(),
    }


async def stream_chat_with_article(
    router: ProfileModelRouter,
    chat_repo: NewsChatRepo,
    *,
    article: dict[str, Any],
    message: str,
    quote: str | None = None,
    web_search_provider: str = "ddgs",
    tavily_api_key: str | None = None,
    web_search_enabled: bool = True,
    prompts: PromptsConfig | None = None,
) -> AsyncIterator[dict[str, Any]]:
    try:
        history = chat_repo.list_messages(article["id"])[-HISTORY_LIMIT:]
        context = build_article_context(article)
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
        if evidence.block:
            context = f"{context}\n\n{evidence.block}"
        web_refs = evidence.refs
        base_messages = _news_messages(context, message, quote, prompts)
        messages = _with_history(base_messages, history)

        chat_repo.add_message(article["id"], "user", message)

        stream = await router.chat(messages, profile="chat", stream=True, json_mode=True)
        assert not isinstance(stream, str)

        buffer = ""
        async for chunk in stream:
            buffer += chunk
            yield {"type": "token", "content": chunk}

        parsed = parse_chat_response(buffer)
        answer = parsed.get("answer", buffer)
        web_from_llm = parsed.get("web_refs") or web_refs

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
            **router.chat_metrics(),
        }
    except Exception as exc:
        yield {
            "type": "error",
            "message": f"深聊失败：{exc}",
        }
