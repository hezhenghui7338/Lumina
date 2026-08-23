"""Progress / cancel helpers for CPU-heavy ingest (keep the sidecar event loop alive)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

OcrProgressCallback = Callable[[int, int, str], None]


class DocumentLoadCancelled(RuntimeError):
    """User cancelled import or resegment while extracting a document."""


def yield_ui() -> None:
    """Release the GIL so HTTP/SSE can run during pypdf/OCR."""
    time.sleep(0)


def check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise DocumentLoadCancelled("已取消")


def report_progress(
    on_progress: OcrProgressCallback | None,
    page: int,
    total: int,
    message: str,
    cancel_event: threading.Event | None = None,
) -> None:
    check_cancel(cancel_event)
    if on_progress:
        on_progress(page, total, message)
    yield_ui()
