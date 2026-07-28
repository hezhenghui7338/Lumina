"""Application state."""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from lumina_core.config import ModelsConfig, Settings, apply_env_keys, default_data_dir, load_models_config
from lumina_core.db.schema import init_db
from lumina_core.jobs.queue import JobQueue
from lumina_core.models.router import ProfileModelRouter
from lumina_core.news.store import NewsSourceRepo
from lumina_core.settings_store import load_settings

DEFAULT_RSS = [
    ("https://hnrss.org/frontpage", "Hacker News"),
    ("https://feeds.arstechnica.com/arstechnica/index", "Ars Technica"),
]


@dataclass
class AppState:
    settings: Settings
    models: ModelsConfig
    conn: sqlite3.Connection
    router: ProfileModelRouter
    job_queue: JobQueue
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
    models = apply_env_keys(load_models_config())
    conn = init_db(settings.data_dir / "lumina.db")
    NewsSourceRepo(conn).ensure_defaults(DEFAULT_RSS)
    router = ProfileModelRouter(models)
    job_queue = JobQueue(
        conn,
        router,
        models.job_concurrency,
        target_language=settings.target_language,
    )
    return AppState(
        settings=settings,
        models=models,
        conn=conn,
        router=router,
        job_queue=job_queue,
    )
