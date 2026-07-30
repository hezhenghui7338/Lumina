"""Thread-safe helpers for the shared SQLite connection."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator

# sqlite3.Connection cannot hold custom attrs or weakrefs (py3.12+).
_CONN_LOCKS: dict[int, threading.RLock] = {}


def attach_db_lock(conn: sqlite3.Connection) -> threading.RLock:
    """Register conn for serialized writes (idempotent)."""
    key = id(conn)
    lock = _CONN_LOCKS.get(key)
    if lock is None:
        lock = threading.RLock()
        _CONN_LOCKS[key] = lock
    return lock


def db_lock(conn: sqlite3.Connection) -> threading.RLock:
    return attach_db_lock(conn)


@contextmanager
def db_transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Serialize writes on the shared connection; commit or rollback atomically."""
    with db_lock(conn):
        try:
            yield conn
            if conn.in_transaction:
                conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
