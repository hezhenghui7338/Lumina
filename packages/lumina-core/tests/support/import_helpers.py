"""Shared helpers for async book import in tests."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

BOOK_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "books"


def wait_for_ingest(
    client: TestClient, book_id: str, *, timeout: float = 5.0
) -> dict:
    """Poll GET /books/{id} until status != processing."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        book = client.get(f"/books/{book_id}").json()
        if book.get("status") not in ("processing",):
            return book
        time.sleep(0.05)
    raise AssertionError(f"ingest timed out for book {book_id}")


def import_sample_book(
    client: TestClient,
    *,
    wait: bool = True,
    sample_name: str = "sample.txt",
) -> str:
    """POST /books/import; optionally wait for ingest; return book_id."""
    sample = BOOK_FIXTURES / sample_name
    resp = client.post("/books/import", json={"paths": [str(sample)]})
    assert resp.status_code == 200
    book_id = resp.json()["books"][0]["book_id"]
    if wait:
        wait_for_ingest(client, book_id)
    return book_id
