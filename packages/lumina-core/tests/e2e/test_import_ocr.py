"""E2E-ingest-ocr: scanned PDF import through OCR pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumina_core.config import Settings
from lumina_core.main import create_app
from lumina_core.models.router import set_router
from tests.support.import_helpers import wait_for_ingest
from tests.support.mock_router import MockModelRouter, load_json_fixture
from tests.support.ocr_helpers import fake_ocr_pdf, write_blank_pdf

pytestmark = pytest.mark.e2e

LLM_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "llm"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMINA_DATA_DIR", str(tmp_path))
    router = MockModelRouter(
        responses={
            "summarize": load_json_fixture(LLM_FIXTURES / "summary_segment0.json"),
        }
    )
    app = create_app(Settings(data_dir=tmp_path))
    app.state.lumina.router = router
    app.state.lumina.job_queue.router = router
    set_router(router)
    with TestClient(app) as c:
        yield c


def test_e2e_ingest_ocr_scanned_pdf(client, tmp_path, monkeypatch):
    """E2E-ingest-ocr: blank PDF triggers OCR and produces readable segments."""
    monkeypatch.setattr("lumina_core.ingest.pdf.ocr_pdf", fake_ocr_pdf)
    pdf = tmp_path / "scan.pdf"
    write_blank_pdf(pdf)

    resp = client.post("/books/import", json={"paths": [str(pdf)]})
    assert resp.status_code == 200
    book_id = resp.json()["books"][0]["book_id"]
    assert resp.json()["books"][0]["status"] == "processing"

    book = wait_for_ingest(client, book_id, timeout=10.0)
    assert book["status"] != "error"
    assert book.get("segment_count", 0) > 0

    segments = client.get(f"/books/{book_id}/segments").json()["segments"]
    assert segments
    seg0 = client.get(f"/books/{book_id}/segments/0").json()
    assert "扫描页" in seg0["raw_text"]
    assert "## [p.1]" in seg0["raw_text"]


def test_e2e_ingest_ocr_failure_marks_book_error(client, tmp_path, monkeypatch):
    """OCR runtime failure surfaces as book status=error (ingest_failed)."""
    def boom(_path, **_kwargs):
        raise RuntimeError("扫描版 PDF OCR 失败: cv2 missing")

    monkeypatch.setattr("lumina_core.ingest.pdf.ocr_pdf", boom)
    pdf = tmp_path / "broken-scan.pdf"
    write_blank_pdf(pdf, pages=1)

    book_id = client.post("/books/import", json={"paths": [str(pdf)]}).json()["books"][0]["book_id"]
    book = wait_for_ingest(client, book_id, timeout=10.0)
    assert book["status"] == "error"
