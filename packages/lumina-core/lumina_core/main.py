"""lumina-core FastAPI application."""

from __future__ import annotations

import argparse
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from lumina_core.api.routes import router
from lumina_core.app_state import AppState, create_app_state
from lumina_core.config import Settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    state: AppState = app.state.lumina
    await state.router.aclose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    state = create_app_state(settings)
    app = FastAPI(title="lumina-core", version="0.1.0", lifespan=lifespan)
    app.state.lumina = state
    app.include_router(router)
    return app


def cli() -> None:
    parser = argparse.ArgumentParser(description="Lumina core sidecar")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=17432)
    args = parser.parse_args()
    settings = Settings(host=args.host, port=args.port)
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
