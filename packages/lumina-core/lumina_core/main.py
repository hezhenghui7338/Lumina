"""lumina-core FastAPI application."""

from __future__ import annotations

import argparse
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from lumina_core.api.routes import router
from lumina_core.api.ops_routes import router as ops_router
from lumina_core.app_state import AppState, create_app_state
from lumina_core.config import Settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    state: AppState = app.state.lumina
    from lumina_core.api.routes import _wire_job_events

    _wire_job_events(state)
    await state.job_queue.recover_on_startup()
    yield
    await state.job_queue.stop_all()
    await state.router.aclose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    state = create_app_state(settings)
    app = FastAPI(title="lumina-core", version="0.8.1", lifespan=lifespan)
    app.state.lumina = state
    app.include_router(router)
    app.include_router(ops_router)
    return app


def smoke_ocr() -> int:
    """Verify OCR optional deps load (used by release build after prune-sidecar)."""
    from lumina_core.ingest.ocr import ocr_dependency_warning

    warning = ocr_dependency_warning()
    if warning:
        print(f"ERROR: OCR smoke failed: {warning}", flush=True)
        return 1
    print("OCR smoke OK", flush=True)
    return 0


def cli() -> None:
    parser = argparse.ArgumentParser(description="Lumina core sidecar")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=17432)
    parser.add_argument(
        "--smoke-ocr",
        action="store_true",
        help="Verify OCR deps load and exit (release build smoke test)",
    )
    args = parser.parse_args()
    if args.smoke_ocr:
        raise SystemExit(smoke_ocr())
    settings = Settings(host=args.host, port=args.port)
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
