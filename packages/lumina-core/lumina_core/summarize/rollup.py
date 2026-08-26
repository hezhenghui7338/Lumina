"""Hierarchical summary rollup: pack segment summaries until they fit one chunk."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from lumina_core.config import PromptsConfig, format_prompt, load_prompts_config, resolve_chunk_budget
from lumina_core.db.repos import BookRepo, SegmentRepo, SummaryNodeRepo
from lumina_core.models.router import ProfileModelRouter
from lumina_core.prompts_defaults import DEFAULT_ROLLUP
from lumina_core.summarize.schema import (
    format_summary_text,
    parse_segment_summary_minimal,
)
from lumina_core.summarize.segment import summary_to_json
from lumina_core.translate.language import language_display_name


logger = logging.getLogger(__name__)


def _dump_summary(summary: Any) -> str:
    return summary_to_json(summary)


@dataclass
class PackItem:
    text: str
    idx_start: int
    idx_end: int
    chapter: str | None = None
    label: str = ""
    segment_id: str | None = None
    summary_json: str | None = None
    children: list[PackItem] = field(default_factory=list)
    node_id: str = field(default_factory=lambda: str(uuid.uuid4()))


def summary_plain_text(summary_json: Any, *, label: str = "") -> str:
    """Flatten stored summary JSON into a compact rollup input string."""
    try:
        parsed = json.loads(summary_json) if isinstance(summary_json, str) else summary_json
    except (TypeError, json.JSONDecodeError):
        parsed = None
    if not isinstance(parsed, dict):
        raw = str(summary_json or "").strip()
        return f"{label} {raw}".strip() if label else raw
    parts = [str(item).strip() for item in parsed.get("sentences", []) if str(item).strip()]
    for bullet in parsed.get("bullets", []):
        if not isinstance(bullet, dict):
            continue
        blabel = str(bullet.get("label") or "").strip()
        body = str(bullet.get("body") or "").strip()
        if body:
            parts.append(f"{blabel}：{body}" if blabel else body)
    if not parts:
        return ""
    text = " ".join(parts)
    heading = label or str(parsed.get("label") or "").strip()
    if heading and text:
        return f"{heading}：{text}"
    return heading or text


def concat_chars(items: list[PackItem]) -> int:
    if not items:
        return 0
    return sum(len(item.text) for item in items) + max(0, len(items) - 1)


def group_by_chapter(items: list[PackItem]) -> list[list[PackItem]]:
    groups: list[list[PackItem]] = []
    current: list[PackItem] = []
    current_chapter: str | None = None
    started = False
    for item in items:
        chapter = (item.chapter or "").strip() or None
        if started and chapter != current_chapter:
            groups.append(current)
            current = []
        started = True
        current_chapter = chapter
        current.append(item)
    if current:
        groups.append(current)
    return groups


def pack_sequential(items: list[PackItem], max_chars: int) -> list[list[PackItem]]:
    if max_chars <= 0:
        return [items] if items else []
    windows: list[list[PackItem]] = []
    current: list[PackItem] = []
    size = 0
    for item in items:
        tlen = len(item.text)
        extra = 1 if current else 0
        if current and size + extra + tlen > max_chars:
            windows.append(current)
            current = []
            size = 0
            extra = 0
        current.append(item)
        size += extra + tlen
    if current:
        windows.append(current)
    return windows


def pack_by_chapter(items: list[PackItem], max_chars: int) -> list[list[PackItem]]:
    windows: list[list[PackItem]] = []
    for group in group_by_chapter(items):
        windows.extend(pack_sequential(group, max_chars))
    return windows


def next_windows(items: list[PackItem], max_chars: int) -> list[list[PackItem]] | None:
    """Return child windows to synthesize, or None to synthesize `items` as one parent."""
    if len(items) <= 1 or concat_chars(items) <= max_chars:
        return None
    windows = pack_by_chapter(items, max_chars)
    if len(windows) <= 1:
        return None
    return windows


def leaves_from_segments(rows: list[dict[str, Any]]) -> list[PackItem]:
    leaves: list[PackItem] = []
    for row in rows:
        idx = int(row["idx"])
        label = str(row.get("label") or f"段 {idx + 1}")
        text = summary_plain_text(row.get("summary_json"), label=label)
        if not text:
            continue
        leaves.append(
            PackItem(
                text=text,
                idx_start=idx,
                idx_end=idx,
                chapter=(row.get("chapter") or "").strip() or None,
                label=label,
                segment_id=row.get("id"),
                summary_json=row.get("summary_json")
                if isinstance(row.get("summary_json"), str)
                else json.dumps(row.get("summary_json") or {}, ensure_ascii=False),
            )
        )
    return leaves


def _range_label(items: list[PackItem]) -> str:
    start = min(i.idx_start for i in items) + 1
    end = max(i.idx_end for i in items) + 1
    if start == end:
        return f"段 {start}"
    return f"段 {start}–{end}"


def _shared_chapter(items: list[PackItem]) -> str | None:
    chapters = {(i.chapter or "").strip() or None for i in items}
    if len(chapters) == 1:
        return next(iter(chapters))
    return None


def format_window_text(items: list[PackItem], *, max_chars: int) -> str:
    parts: list[str] = []
    for item in items:
        heading = _range_label([item])
        if item.label and item.label not in heading:
            heading = f"{heading} · {item.label}"
        parts.append(f"[{heading}]\n{item.text}")
    joined = "\n\n".join(parts)
    if len(joined) > max_chars:
        return joined[:max_chars].rstrip()
    return joined


async def synthesize_window(
    router: ProfileModelRouter,
    items: list[PackItem],
    *,
    max_chars: int,
    prompts: PromptsConfig | None = None,
    target_language: str = "zh-CN",
) -> tuple[str, str, str]:
    """Return (summary_json, label, plain_text) for a packed window."""
    resolved = prompts or load_prompts_config()
    template = resolved.rollup or DEFAULT_ROLLUP
    body = format_window_text(items, max_chars=max_chars)
    prompt = format_prompt(
        template,
        text=body,
        target_language=language_display_name(target_language),
    )
    fallback_anchor = _range_label(items)
    try:
        raw = await router.complete(prompt, profile="summarize", json_mode=True)
        summary = parse_segment_summary_minimal(raw, fallback_anchor=fallback_anchor)
        dumped = _dump_summary(summary)
        label = (summary.label or fallback_anchor)[:20]
        plain = format_summary_text(summary)
        return dumped, label, plain
    except Exception as exc:
        logger.warning("rollup synthesize failed (%s): %s", fallback_anchor, exc)
        sentences = [item.text[:80] for item in items[:3] if item.text]
        payload = {
            "sentences": sentences[:3] or [fallback_anchor],
            "bullets": [
                {"label": (item.label or "要点")[:8], "body": item.text[:120] or fallback_anchor}
                for item in items[:5]
            ]
            or [{"label": "要点", "body": fallback_anchor}],
            "follow_ups": [],
            "label": fallback_anchor[:20],
            "anchor": fallback_anchor,
        }
        dumped = json.dumps(payload, ensure_ascii=False)
        return dumped, fallback_anchor[:20], " ".join(sentences) or fallback_anchor


def assign_levels(root: PackItem) -> None:
    """Set implicit levels via a BFS attribute on each node (`_level`)."""
    queue: list[tuple[PackItem, int]] = [(root, 0)]
    while queue:
        node, level = queue.pop(0)
        setattr(node, "_level", level)
        for child in node.children:
            queue.append((child, level + 1))


def flatten_nodes(root: PackItem, book_id: str) -> list[dict[str, Any]]:
    assign_levels(root)
    out: list[dict[str, Any]] = []
    sort_by_level: dict[int, int] = {}

    def walk(node: PackItem, parent_id: str | None) -> None:
        level = int(getattr(node, "_level", 0))
        sort_idx = sort_by_level.get(level, 0)
        sort_by_level[level] = sort_idx + 1
        out.append(
            {
                "id": node.node_id,
                "book_id": book_id,
                "level": level,
                "parent_id": parent_id,
                "sort_idx": sort_idx,
                "segment_id": node.segment_id,
                "segment_idx_start": node.idx_start,
                "segment_idx_end": node.idx_end,
                "chapter": node.chapter,
                "label": node.label,
                "summary_json": node.summary_json,
                "status": "ready",
            }
        )
        for child in node.children:
            walk(child, node.node_id)

    walk(root, None)
    return out


async def build_rollup_tree(
    router: ProfileModelRouter,
    leaves: list[PackItem],
    *,
    max_chars: int,
    prompts: PromptsConfig | None = None,
    cancelled: Callable[[], bool] | None = None,
    on_progress: Callable[[dict[str, Any]], Any] | None = None,
    target_language: str = "zh-CN",
) -> PackItem:
    if not leaves:
        raise ValueError("no ready segment summaries to roll up")

    async def _progress(payload: dict[str, Any]) -> None:
        if on_progress is None:
            return
        result = on_progress(payload)
        if hasattr(result, "__await__"):
            await result

    current = leaves
    while True:
        if cancelled and cancelled():
            raise InterruptedError("book index cancelled")
        windows = next_windows(current, max_chars)
        if windows is None:
            break
        parents: list[PackItem] = []
        for window in windows:
            if cancelled and cancelled():
                raise InterruptedError("book index cancelled")
            dumped, label, plain = await synthesize_window(
                router,
                window,
                max_chars=max_chars,
                prompts=prompts,
                target_language=target_language,
            )
            parent = PackItem(
                text=plain,
                idx_start=min(i.idx_start for i in window),
                idx_end=max(i.idx_end for i in window),
                chapter=_shared_chapter(window),
                label=label,
                summary_json=dumped,
                children=list(window),
            )
            parents.append(parent)
            await _progress(
                {
                    "type": "book_index_progress",
                    "phase": "cluster",
                    "segment_idx_start": parent.idx_start,
                    "segment_idx_end": parent.idx_end,
                }
            )
        current = parents

    dumped, label, plain = await synthesize_window(
        router,
        current,
        max_chars=max_chars,
        prompts=prompts,
        target_language=target_language,
    )
    root = PackItem(
        text=plain,
        idx_start=min(i.idx_start for i in current),
        idx_end=max(i.idx_end for i in current),
        chapter=_shared_chapter(current),
        label=(label or "全书")[:20],
        summary_json=dumped,
        children=list(current),
    )
    return root


async def rollup_book(
    conn,
    router: ProfileModelRouter,
    book_id: str,
    *,
    prompts: PromptsConfig | None = None,
    cancelled: Callable[[], bool] | None = None,
    on_progress: Callable[[dict[str, Any]], Any] | None = None,
    target_language: str | None = None,
) -> str:
    """Build and persist the summary tree. Returns index_status."""
    books = BookRepo(conn)
    segments = SegmentRepo(conn)
    nodes = SummaryNodeRepo(conn)
    book = await asyncio.to_thread(books.get, book_id)
    if not book:
        return "idle"

    models = getattr(router, "models", None)
    max_chars = resolve_chunk_budget(models).max_chars
    effective_language = (
        (book.get("target_language") or "").strip()
        or (target_language or "").strip()
        or "zh-CN"
    )
    rows = await asyncio.to_thread(segments.list_ready_summaries, book_id)
    leaves = leaves_from_segments(rows)
    if not leaves:

        def _mark_error() -> None:
            nodes.delete_for_book(book_id)
            books.update(book_id, index_status="error")

        await asyncio.to_thread(_mark_error)
        return "error"

    await asyncio.to_thread(books.update, book_id, index_status="building")
    try:
        root = await build_rollup_tree(
            router,
            leaves,
            max_chars=max_chars,
            prompts=prompts,
            cancelled=cancelled,
            on_progress=on_progress,
            target_language=effective_language,
        )
        persisted = flatten_nodes(root, book_id)

        def _persist_ready() -> None:
            nodes.replace_for_book(book_id, persisted)
            books.update(book_id, index_status="ready")

        await asyncio.to_thread(_persist_ready)
        return "ready"
    except InterruptedError:

        def _mark_idle() -> None:
            nodes.delete_for_book(book_id)
            books.update(book_id, index_status="idle")

        await asyncio.to_thread(_mark_idle)
        return "idle"
    except Exception:
        logger.exception("book index rollup failed for %s", book_id)

        def _mark_failed() -> None:
            nodes.delete_for_book(book_id)
            books.update(book_id, index_status="error")

        await asyncio.to_thread(_mark_failed)
        return "error"
