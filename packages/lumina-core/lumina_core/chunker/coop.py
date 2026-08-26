"""Cooperative cancel + GIL yield for CPU-bound chunking.

`asyncio.to_thread` does not release the GIL for Python bytecode. A tight
chunker loop would starve uvicorn, so GET /health /books /news hang and the
desktop UI looks frozen. `time.sleep(0)` often fails to schedule the event
loop under a hot bytecode loop; a 1ms sleep every few tens of thousands of
characters lets /health run. The `--cpu-worker` child has its own GIL, so
sleeps there only waste time (`LUMINA_CPU_WORKER=1`).
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Iterator
from typing import Callable

# ~2–4 万字 between yields (plan: huge-book ingest must not pin the GIL).
GIL_YIELD_CHARS = 32_000
# sleep(0) does not reliably hand off the GIL; 1ms does.
GIL_YIELD_SECONDS = 0.001
CPU_WORKER_ENV = "LUMINA_CPU_WORKER"
# Above this, skip Ollama/ONNX embeddings and use the lexical scorer only.
LARGE_ATOM_EMBED_LIMIT = 4096
LARGE_TEXT_EMBED_CHARS = 500_000
PROGRESS_INTERVAL_SECONDS = 0.5

ProgressFn = Callable[[str], None]
CharProgressFn = Callable[[int, int, str], None]


def coerce_char_progress(on_progress: CharProgressFn | ProgressFn | None) -> CharProgressFn | None:
    """Accept (page, total, message) or legacy (message,) callbacks."""
    if on_progress is None:
        return None

    def wrapped(page: int, total: int, message: str) -> None:
        try:
            on_progress(page, total, message)  # type: ignore[misc]
        except TypeError:
            on_progress(message)  # type: ignore[misc]

    return wrapped


def _gil_yield_seconds() -> float:
    if os.environ.get(CPU_WORKER_ENV, "").strip() in ("1", "true", "yes"):
        return 0.0
    return GIL_YIELD_SECONDS


class GilYielder:
    """Bump character/work counts; periodically sleep and honor cancel."""

    def __init__(
        self,
        cancel_event: threading.Event | None = None,
        *,
        every: int = GIL_YIELD_CHARS,
        on_progress: CharProgressFn | None = None,
        progress_total: int = 0,
        progress_message: str = "",
    ) -> None:
        self.cancel_event = cancel_event
        self.every = max(1, every)
        self._since = 0
        self._sleep = _gil_yield_seconds()
        self._on_progress = on_progress
        self._progress_total = max(0, progress_total)
        self._progress_message = progress_message
        self._progressed = 0
        self._last_report = 0.0

    def set_stage(self, message: str, *, reset: bool = True) -> None:
        self._progress_message = message
        if reset:
            self._progressed = 0
        self._report(force=True)

    def ensure_total(self, total: int) -> None:
        if self._progress_total <= 0 and total > 0:
            self._progress_total = total

    def check(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise InterruptedError("cancelled")

    def bump(self, amount: int = 1) -> None:
        self.check()
        if amount <= 0:
            return
        self._since += amount
        self._progressed += amount
        while self._since >= self.every:
            self._since -= self.every
            if self._sleep > 0:
                time.sleep(self._sleep)
            self.check()
        self._report(force=False)

    def _report(self, *, force: bool) -> None:
        if self._on_progress is None:
            return
        now = time.monotonic()
        total = self._progress_total or self._progressed
        if (
            not force
            and self._progressed < total
            and now - self._last_report < PROGRESS_INTERVAL_SECONDS
        ):
            return
        self._last_report = now
        done = min(self._progressed, total) if total else self._progressed
        self._on_progress(done, total, self._progress_message)


class ScanProgress:
    """Throttle (page, total, message) reports for ingest SSE."""

    def __init__(
        self,
        callback: CharProgressFn | None,
        total: int,
        message: str = "",
        *,
        min_interval: float = PROGRESS_INTERVAL_SECONDS,
    ) -> None:
        self.callback = callback
        self.total = max(0, total)
        self.message = message
        self.min_interval = min_interval
        self._last = 0.0

    def emit(self, done: int, message: str | None = None, *, force: bool = False) -> None:
        if message is not None:
            self.message = message
        if self.callback is None:
            return
        now = time.monotonic()
        total = self.total if self.total > 0 else max(done, 1)
        if not force and done < total and now - self._last < self.min_interval and done > 0:
            return
        self._last = now
        self.callback(min(done, total) if total else done, total, self.message)


def iter_text_lines(
    text: str,
    yielder: GilYielder | None = None,
) -> Iterator[tuple[int, str]]:
    """Yield (line_start, line) without a full-text regex. Splits ``\\n`` / ``\\r`` / ``\\r\\n``."""
    start = 0
    n = len(text)
    has_cr = "\r" in text
    has_lf = "\n" in text
    if not has_cr and not has_lf:
        if yielder is not None:
            yielder.bump(n or 1)
        yield 0, text
        return
    while start < n:
        lf = text.find("\n", start) if has_lf else -1
        cr = text.find("\r", start) if has_cr else -1
        if lf == -1 and cr == -1:
            line = text[start:]
            if yielder is not None:
                yielder.bump(len(line) or 1)
            yield start, line
            return
        if cr != -1 and (lf == -1 or cr < lf):
            line = text[start:cr]
            nxt = cr + 1
            if nxt < n and text[nxt] == "\n":
                nxt += 1
            consumed = nxt - start
        else:
            line = text[start:lf]
            if line.endswith("\r"):
                line = line[:-1]
            nxt = lf + 1
            consumed = nxt - start
        if yielder is not None:
            yielder.bump(consumed or 1)
        yield start, line
        start = nxt
