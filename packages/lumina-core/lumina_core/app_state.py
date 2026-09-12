"""Application state."""

from __future__ import annotations

import asyncio
import sqlite3
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lumina_core.config import ModelsConfig, PromptsConfig, Settings
from lumina_core.db.schema import init_db
from lumina_core.jobs.queue import JobQueue
from lumina_core.models.concurrency import ResourceConcurrencyGate
from lumina_core.models.router import ProfileModelRouter
from lumina_core.news.store import NewsSourceRepo
from lumina_core.ops.task_registry import TaskRegistry
from lumina_core.settings_store import hydrate_startup_settings, load_models

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


# Cold-start news sync wall clock (PRD §3.5 / §5.8).
BOOT_NEWS_SYNC_TIMEOUT_S = 60.0


@dataclass
class AppState:
    settings: Settings
    models: ModelsConfig
    conn: sqlite3.Connection
    concurrency_gate: ResourceConcurrencyGate
    router: ProfileModelRouter
    job_queue: JobQueue
    task_registry: TaskRegistry
    event_subscribers: dict[str, list[asyncio.Queue]] = field(default_factory=dict)
    resegment_tasks: dict[str, asyncio.Task[str]] = field(default_factory=dict)
    resegment_cancel_events: dict[str, threading.Event] = field(default_factory=dict)
    ingest_tasks: dict[str, asyncio.Task[str]] = field(default_factory=dict)
    ingest_cancel_events: dict[str, threading.Event] = field(default_factory=dict)
    context_probe_tasks: dict[str, asyncio.Task[Any]] = field(default_factory=dict)
    context_probe_cancel: dict[str, asyncio.Event] = field(default_factory=dict)
    context_probe_status: dict[str, Any] = field(default_factory=dict)
    cpu_job_lock: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(1))
    # Cold-start gate: pending|running|done|failed
    startup_news_phase: str = "pending"
    startup_news_detail: str | None = None
    _boot_news_task: asyncio.Task[None] | None = field(default=None, repr=False)

    @property
    def db_path(self) -> Path:
        return self.settings.data_dir / "lumina.db"

    @property
    def books_dir(self) -> Path:
        return self.settings.data_dir / "books"

    def startup_status(self) -> dict[str, Any]:
        """Product-ready phases for the cold-start gate (not process liveness)."""
        return {
            "engine": "ready",
            "data": self.job_queue.startup_data_phase(),
            "cache": self.job_queue.startup_cache_phase(),
            "news": self.startup_news_phase,
            "news_detail": self.startup_news_detail,
        }

    async def run_boot_news_sync(self) -> None:
        """One-shot RSS sync after cache phase; never blocks /health.

        Uses a daemon thread (not asyncio.to_thread): cancelling / shutting down
        must not leave a non-daemon pool worker in httpx.get holding the process
        open after POST /shutdown.
        """
        if self.startup_news_phase in ("done", "failed", "running"):
            return
        self.startup_news_phase = "running"
        self.startup_news_detail = None
        from lumina_core.news.sync import sync_all

        loop = asyncio.get_running_loop()
        result_fut: asyncio.Future[Any] = loop.create_future()

        def _run() -> None:
            try:
                value = sync_all(self.conn)
            except Exception as exc:  # noqa: BLE001 — delivered via future
                def _fail(err: BaseException = exc) -> None:
                    if not result_fut.done():
                        result_fut.set_exception(err)

                try:
                    loop.call_soon_threadsafe(_fail)
                except RuntimeError:
                    # Loop already closed after cancel/shutdown — abandon result.
                    return
            else:
                def _ok(result: Any = value) -> None:
                    if not result_fut.done():
                        result_fut.set_result(result)

                try:
                    loop.call_soon_threadsafe(_ok)
                except RuntimeError:
                    return

        threading.Thread(
            target=_run, name="lumina-boot-news", daemon=True
        ).start()

        try:
            results = await asyncio.wait_for(
                result_fut, timeout=BOOT_NEWS_SYNC_TIMEOUT_S
            )
            errors = [r.error for r in results if r.error]
            if errors:
                self.startup_news_phase = "failed"
                self.startup_news_detail = "; ".join(errors[:3])
            else:
                self.startup_news_phase = "done"
        except asyncio.TimeoutError:
            if not result_fut.done():
                result_fut.cancel()
            self.startup_news_phase = "failed"
            self.startup_news_detail = "timeout"
        except asyncio.CancelledError:
            if not result_fut.done():
                result_fut.cancel()
            if self.startup_news_phase == "running":
                self.startup_news_phase = "failed"
                self.startup_news_detail = "cancelled"
            raise
        except Exception as exc:
            self.startup_news_phase = "failed"
            self.startup_news_detail = str(exc)[:200]


def create_app_state(settings: Settings | None = None) -> AppState:
    from lumina_core.perf import record as perf_record
    from lumina_core.perf import start as perf_start

    t0 = time.perf_counter()
    settings = hydrate_startup_settings(settings)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    perf_start(settings.data_dir)
    models = load_models(settings.data_dir)
    t_hydrate = time.perf_counter()
    hydrate_ms = (t_hydrate - t0) * 1000.0
    perf_record(kind="op", name="startup.hydrate", ms=hydrate_ms)
    conn = init_db(settings.data_dir / "lumina.db")
    NewsSourceRepo(conn).ensure_defaults(default_rss_sources(settings.target_language))
    t_db = time.perf_counter()
    init_db_ms = (t_db - t_hydrate) * 1000.0
    perf_record(kind="op", name="startup.init_db", ms=init_db_ms)
    concurrency_gate = ResourceConcurrencyGate(models.resources)
    router = ProfileModelRouter(models, gate=concurrency_gate)
    task_registry = TaskRegistry()
    job_queue = JobQueue(
        conn,
        router,
        target_language=settings.target_language,
        auto_start_summary=settings.auto_start_summary,
        task_registry=task_registry,
        prompts=settings.prompts,
    )
    t_done = time.perf_counter()
    assemble_ms = (t_done - t_db) * 1000.0
    total_ms = (t_done - t0) * 1000.0
    perf_record(kind="op", name="startup.assemble", ms=assemble_ms)
    perf_record(kind="op", name="startup.total", ms=total_ms)
    print(
        "lumina-core startup:"
        f" hydrate_ms={int(hydrate_ms)}"
        f" init_db_ms={int(init_db_ms)}"
        f" assemble_ms={int(assemble_ms)}"
        f" total_ms={int(total_ms)}",
        flush=True,
        file=sys.stderr,
    )
    return AppState(
        settings=settings,
        models=models,
        conn=conn,
        concurrency_gate=concurrency_gate,
        router=router,
        job_queue=job_queue,
        task_registry=task_registry,
    )
