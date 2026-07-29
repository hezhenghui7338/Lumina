"""Application state."""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from lumina_core.config import ModelsConfig, Settings, default_data_dir
from lumina_core.db.schema import init_db
from lumina_core.jobs.queue import JobQueue
from lumina_core.models.router import ProfileModelRouter
from lumina_core.news.store import NewsSourceRepo
from lumina_core.ops.task_registry import TaskRegistry
from lumina_core.settings_store import load_models, load_settings

BESTBLOGS_AI_ZH = (
    "https://www.bestblogs.dev/zh/feeds/rss"
    "?category=ai&minScore=80&timeFilter=1d"
)
BESTBLOGS_DAILY_BRIEF = "https://www.bestblogs.dev/zh/feeds/rss/daily-brief"
BESTBLOGS_AI_EN = (
    "https://www.bestblogs.dev/en/feeds/rss"
    "?category=ai&minScore=85&timeFilter=1d"
)

DEFAULT_NEWS_SOURCES: list[tuple[str, str]] = [
    (BESTBLOGS_AI_ZH, "BestBlogs AI · 中文"),
    (BESTBLOGS_DAILY_BRIEF, "BestBlogs 每日早报"),
    (BESTBLOGS_AI_EN, "BestBlogs AI · English"),
]

# Retired preset URLs — pruned on startup; custom sources are never matched here.
OBSOLETE_NEWS_SOURCE_URLS: frozenset[str] = frozenset(
    {
        "https://www.jiqizhixin.com/rss",
        "https://hnrss.org/frontpage",
        "https://hnrss.org/newest?q=AI&count=30",
        "https://feeds.arstechnica.com/arstechnica/index",
        "https://simonwillison.net/atom/everything/",
        "https://techcrunch.com/category/artificial-intelligence/feed/",
        "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
        "https://www.technologyreview.com/topic/artificial-intelligence/feed/",
        "https://deepmind.google/blog/rss.xml",
        "https://blog.google/technology/ai/rss/",
        "https://raw.githubusercontent.com/0xSMW/rss-feeds/main/feeds/feed_anthropic_news.xml",
        "https://raw.githubusercontent.com/alan-turing-institute/ai-rss-feeds/"
        "refs/heads/main/feeds/tldr-ai.xml",
        "https://www.interconnects.ai/feed",
    }
)


def bestblogs_rss_url(target_language: str = "zh-CN") -> str:
    path_lang = "zh" if (target_language or "zh").lower().startswith("zh") else "en"
    if path_lang == "zh":
        return BESTBLOGS_AI_ZH
    return BESTBLOGS_AI_EN


def default_rss_sources(target_language: str = "zh-CN") -> list[tuple[str, str]]:
    """BestBlogs preset feeds; target_language kept for API compatibility."""
    _ = target_language
    return list(DEFAULT_NEWS_SOURCES)


# Backward-compatible alias
DEFAULT_RSS = default_rss_sources("zh-CN")


@dataclass
class AppState:
    settings: Settings
    models: ModelsConfig
    conn: sqlite3.Connection
    router: ProfileModelRouter
    job_queue: JobQueue
    task_registry: TaskRegistry
    event_subscribers: dict[str, list[asyncio.Queue]] = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.settings.data_dir / "lumina.db"

    @property
    def books_dir(self) -> Path:
        return self.settings.data_dir / "books"


def create_app_state(settings: Settings | None = None) -> AppState:
    if settings is None:
        data_dir = default_data_dir()
        settings = load_settings(data_dir)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    models = load_models(settings.data_dir)
    conn = init_db(settings.data_dir / "lumina.db")
    NewsSourceRepo(conn).ensure_defaults(default_rss_sources(settings.target_language))
    router = ProfileModelRouter(models)
    task_registry = TaskRegistry()
    job_queue = JobQueue(
        conn,
        router,
        target_language=settings.target_language,
        task_registry=task_registry,
    )
    return AppState(
        settings=settings,
        models=models,
        conn=conn,
        router=router,
        job_queue=job_queue,
        task_registry=task_registry,
    )
