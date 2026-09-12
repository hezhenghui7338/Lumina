"""lumina-core FastAPI application."""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from lumina_core import __version__
from lumina_core.api.ops_routes import router as ops_router
from lumina_core.api.routes import router
from lumina_core.app_state import AppState, create_app_state
from lumina_core.config import Settings


async def _cold_start_pipeline(state: AppState) -> None:
    """Recover → await deferred cache → one-shot news sync.

    Must run as a background task so GET /health stays reachable (E2E-BOOT-02e).
    """
    await state.job_queue.recover_on_startup()
    deferred = (
        state.job_queue._startup_deferred_task
        or state.job_queue._catalog_backfill_task
    )
    if deferred is not None:
        try:
            await deferred
        except asyncio.CancelledError:
            raise
    if state.job_queue._shutting_down:
        return
    await state.run_boot_news_sync()


@asynccontextmanager
async def lifespan(app: FastAPI):
    state: AppState = app.state.lumina
    from lumina_core.api.routes import _wire_job_events

    _wire_job_events(state)
    # E2E-BOOT-02e: /health must answer before recover finishes. A 180-book
    # library can spend minutes in recover; awaiting it here makes the client
    # time out, kill the process, and the next launch hits database is locked.
    startup_task = asyncio.create_task(
        _cold_start_pipeline(state),
        name="lumina-cold-start",
    )
    yield
    if not startup_task.done():
        startup_task.cancel()
        try:
            await startup_task
        except asyncio.CancelledError:
            pass
    await state.job_queue.shutdown()
    await state.router.aclose()


def create_app(settings: Settings | None = None) -> FastAPI:
    from lumina_core.perf import PerfHTTPMiddleware

    state = create_app_state(settings)
    app = FastAPI(title="lumina-core", version=__version__, lifespan=lifespan)
    app.state.lumina = state
    app.include_router(router)
    app.include_router(ops_router)
    app.add_middleware(PerfHTTPMiddleware)
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
    parser.add_argument(
        "--cpu-worker",
        default=None,
        metavar="JOB.json",
        help="Run ingest/resegment CPU in this process and exit (sidecar child)",
    )
    args = parser.parse_args()
    if args.smoke_ocr:
        raise SystemExit(smoke_ocr())
    if args.cpu_worker:
        from lumina_core.jobs.cpu_worker import run_cpu_job_file

        raise SystemExit(run_cpu_job_file(Path(args.cpu_worker)))
    t_cli = time.perf_counter()
    settings = Settings(host=args.host, port=args.port)
    app = create_app(settings)
    print(
        f"lumina-core startup: create_app_ms={int((time.perf_counter() - t_cli) * 1000)}",
        flush=True,
        file=sys.stderr,
    )
    config = uvicorn.Config(
        app, host=settings.host, port=settings.port, log_level="info"
    )
    server = uvicorn.Server(config)
    app.state.uvicorn_server = server
    server.run()


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
