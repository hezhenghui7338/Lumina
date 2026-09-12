"""Local performance JSONL (default on; one file per process start)."""

from __future__ import annotations

import atexit
import json
import os
import queue
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SQL_VERB_RE = re.compile(
    r"^\s*(WITH|SELECT|INSERT|UPDATE|DELETE|REPLACE|PRAGMA|CREATE|DROP|ALTER|"
    r"BEGIN|COMMIT|ROLLBACK|VACUUM|ANALYZE|ATTACH|DETACH)\b",
    re.IGNORECASE,
)
_TABLE_RE = re.compile(
    r"\b(?:FROM|INTO|UPDATE|TABLE(?:\s+IF\s+NOT\s+EXISTS)?|INDEX(?:\s+IF\s+NOT\s+EXISTS)?)"
    r"\s+[\"'`]?(\w+)",
    re.IGNORECASE,
)
_WS_RE = re.compile(r"\s+")

_SENTINEL = object()
_QUEUE_MAX = 20_000
_SQL_TRUNCATE = 120
_PERF_WRAPPED: set[int] = set()


class _FlushAck:
    __slots__ = ("event",)

    def __init__(self) -> None:
        self.event = threading.Event()


def sql_label(sql: str) -> tuple[str, str]:
    """Return (name, truncated_sql) without bind parameters."""
    compact = _WS_RE.sub(" ", (sql or "").strip())
    verb_m = _SQL_VERB_RE.match(compact)
    verb = verb_m.group(1).upper() if verb_m else "SQL"
    table_m = _TABLE_RE.search(compact)
    table = table_m.group(1) if table_m else None
    name = f"{verb} {table}" if table else verb
    clipped = compact if len(compact) <= _SQL_TRUNCATE else compact[: _SQL_TRUNCATE - 1] + "…"
    return name, clipped


class PerfRecorder:
    """Queue-backed writer: callers never block on disk I/O."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._q: queue.Queue[Any] = queue.Queue(maxsize=_QUEUE_MAX)
        self._path: Path | None = None
        self._file: Any = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._started = False

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def started(self) -> bool:
        return self._started

    def start(self, data_dir: Path) -> Path:
        with self._lock:
            self._stop_writer_locked()
            perf_dir = Path(data_dir) / "perf"
            perf_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
            path = perf_dir / f"session-{ts}-{os.getpid()}.jsonl"
            self._path = path
            self._file = open(path, "a", encoding="utf-8")  # noqa: SIM115
            self._stop.clear()
            self._q = queue.Queue(maxsize=_QUEUE_MAX)
            self._thread = threading.Thread(
                target=self._writer_loop,
                name="lumina-perf-writer",
                daemon=True,
            )
            self._thread.start()
            self._started = True
        self.record(
            kind="session",
            name="start",
            ms=0.0,
            pid=os.getpid(),
            file=str(path),
        )
        return path

    def record(self, kind: str, name: str, ms: float, **fields: Any) -> None:
        if not self._started:
            return
        row: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "kind": kind,
            "name": name,
            "ms": round(float(ms), 3),
        }
        for key, value in fields.items():
            if value is not None:
                row[key] = value
        try:
            self._q.put_nowait(row)
        except queue.Full:
            # Never block request / DB paths.
            return

    def flush(self, timeout: float = 2.0) -> None:
        """Wait until queued rows are on disk (tests / shutdown)."""
        if not self._started:
            return
        ack = _FlushAck()
        try:
            self._q.put(ack, timeout=timeout)
        except queue.Full:
            return
        ack.event.wait(timeout=timeout)

    def stop(self) -> None:
        with self._lock:
            self._stop_writer_locked()

    def _stop_writer_locked(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            try:
                self._q.put_nowait(_SENTINEL)
            except queue.Full:
                self._stop.set()
            self._thread.join(timeout=2.0)
        if self._file is not None:
            try:
                self._file.flush()
                self._file.close()
            except Exception:
                pass
        self._file = None
        self._thread = None
        self._started = False
        self._stop.set()

    def _writer_loop(self) -> None:
        buf: list[str] = []
        last_flush = time.perf_counter()
        while True:
            try:
                item = self._q.get(timeout=0.05)
            except queue.Empty:
                if buf and self._file is not None:
                    self._write_buf(buf)
                    buf = []
                    last_flush = time.perf_counter()
                if self._stop.is_set():
                    break
                continue
            if item is _SENTINEL:
                if buf and self._file is not None:
                    self._write_buf(buf)
                break
            if isinstance(item, _FlushAck):
                if buf and self._file is not None:
                    self._write_buf(buf)
                    buf = []
                item.event.set()
                continue
            buf.append(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
            now = time.perf_counter()
            if len(buf) >= 32 or (now - last_flush) >= 0.05:
                if self._file is not None:
                    self._write_buf(buf)
                buf = []
                last_flush = now

    def _write_buf(self, buf: list[str]) -> None:
        assert self._file is not None
        self._file.write("\n".join(buf) + "\n")
        self._file.flush()


_recorder = PerfRecorder()
atexit.register(_recorder.stop)


def get_recorder() -> PerfRecorder:
    return _recorder


def start(data_dir: Path) -> Path:
    return _recorder.start(data_dir)


def record(kind: str, name: str, ms: float, **fields: Any) -> None:
    _recorder.record(kind, name, ms, **fields)


def flush(timeout: float = 2.0) -> None:
    _recorder.flush(timeout=timeout)


def stop() -> None:
    _recorder.stop()


class InstrumentedConnection:
    """Proxy: sqlite3.Connection.execute is read-only on modern Python."""

    __slots__ = ("_conn",)

    def __init__(self, conn: sqlite3.Connection) -> None:
        object.__setattr__(self, "_conn", conn)

    def execute(self, sql: str, parameters: Any = ()) -> sqlite3.Cursor:
        return self._timed("execute", sql, lambda: self._conn.execute(sql, parameters))

    def executemany(self, sql: str, parameters: Any) -> sqlite3.Cursor:
        return self._timed(
            "executemany", sql, lambda: self._conn.executemany(sql, parameters)
        )

    def executescript(self, sql_script: str) -> sqlite3.Cursor:
        return self._timed(
            "executescript", sql_script, lambda: self._conn.executescript(sql_script)
        )

    def _timed(self, op: str, sql: str, call: Any) -> Any:
        name, clipped = sql_label(sql)
        t0 = time.perf_counter()
        try:
            return call()
        finally:
            _recorder.record(
                kind="db",
                name=name,
                ms=(time.perf_counter() - t0) * 1000.0,
                op=op,
                sql=clipped,
            )

    def __enter__(self) -> InstrumentedConnection:
        # Special methods are not resolved via __getattr__.
        self._conn.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Any:
        return self._conn.__exit__(exc_type, exc_val, exc_tb)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_conn":
            object.__setattr__(self, name, value)
        else:
            setattr(self._conn, name, value)


def instrument_connection(
    conn: sqlite3.Connection | InstrumentedConnection,
) -> InstrumentedConnection:
    """Wrap a connection with timing (idempotent)."""
    if isinstance(conn, InstrumentedConnection):
        return conn
    key = id(conn)
    if key in _PERF_WRAPPED:
        # Should not happen for fresh connects; re-wrap defensively.
        return InstrumentedConnection(conn)
    _PERF_WRAPPED.add(key)
    return InstrumentedConnection(conn)


def forget_instrumented_connection(conn: Any) -> None:
    """Drop wrap bookkeeping when a short-lived connection is closed."""
    raw = conn._conn if isinstance(conn, InstrumentedConnection) else conn
    _PERF_WRAPPED.discard(id(raw))
    _PERF_WRAPPED.discard(id(conn))


def _header_value(headers: list[tuple[bytes, bytes]], name: bytes) -> str | None:
    name_l = name.lower()
    for key, value in headers:
        if key.lower() == name_l:
            return value.decode("latin-1")
    return None


class PerfHTTPMiddleware:
    """Pure ASGI middleware: time HTTP; SSE records TTFB + stream separately."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        path = scope.get("path", "")
        t0 = time.perf_counter()
        status_code = 0
        streaming = False
        ttfb_ms: float | None = None

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal status_code, streaming, ttfb_ms
            if message["type"] == "http.response.start":
                status_code = int(message.get("status", 0))
                ctype = _header_value(list(message.get("headers") or []), b"content-type")
                if ctype and "text/event-stream" in ctype.lower():
                    streaming = True
                ttfb_ms = (time.perf_counter() - t0) * 1000.0
                if streaming:
                    _recorder.record(
                        kind="http",
                        name=f"{method} {path}",
                        ms=ttfb_ms,
                        method=method,
                        path=path,
                        status=status_code,
                        streaming=True,
                        phase="ttfb",
                    )
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            total_ms = (time.perf_counter() - t0) * 1000.0
            if streaming:
                _recorder.record(
                    kind="http",
                    name=f"{method} {path}",
                    ms=total_ms,
                    method=method,
                    path=path,
                    status=status_code,
                    streaming=True,
                    phase="stream",
                    ttfb_ms=ttfb_ms,
                )
            else:
                _recorder.record(
                    kind="http",
                    name=f"{method} {path}",
                    ms=total_ms,
                    method=method,
                    path=path,
                    status=status_code,
                )
