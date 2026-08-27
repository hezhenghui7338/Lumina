"""Run ingest/resegment CPU in a sidecar child process.

CPython holds the GIL across ``bytes.decode``, ``re.finditer`` on multi-MB
text, and SQLite FTS writes. ``asyncio.to_thread`` plus cooperative
``time.sleep`` cannot keep GET /health, /books, /news, /settings alive
while that work runs in the API process. A child process has its own GIL.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from lumina_core.config import ModelsConfig, Settings, normalize_segment_tier
from lumina_core.ingest.progress import DocumentLoadCancelled

logger = logging.getLogger(__name__)

# ~256 KiB: small fixtures stay in-process; a 13MB TXT always offloads.
CPU_PROCESS_MIN_BYTES = 256 * 1024
INLINE_ENV = "LUMINA_CPU_INLINE"
STALL_ENV = "LUMINA_CPU_STALL_SECONDS"
JOB_MAX_ENV = "LUMINA_CPU_JOB_MAX_SECONDS"
CPU_STALL_SECONDS = 180.0
CPU_JOB_MAX_FLOOR_SECONDS = 1800.0
CPU_JOB_MAX_CEILING_SECONDS = 8 * 3600.0
CPU_JOB_SECONDS_PER_PAGE = 60.0
CPU_JOB_SECONDS_PER_MIB = 30.0
CPU_JOB_MAX_PLAUSIBLE_PAGES = 20_000
PAGE_PROGRESS_FORMATS = frozenset({"pdf"})
CPU_WORKER_ENV = "LUMINA_CPU_WORKER"
_MIB = 1024 * 1024

ProgressFn = Callable[[int, int, str], None]


def should_offload_cpu(path: Path) -> bool:
    if os.environ.get(INLINE_ENV, "").strip().lower() in ("1", "true", "yes"):
        return False
    try:
        return path.stat().st_size >= CPU_PROCESS_MIN_BYTES
    except OSError:
        return False


def cpu_worker_command(job_path: Path) -> list[str]:
    job = str(job_path)
    if getattr(sys, "frozen", False):
        return [sys.executable, "--cpu-worker", job]
    # Unfrozen: skip FastAPI import in the child. Frozen sidecar uses the same binary.
    return [sys.executable, "-m", "lumina_core.jobs.cpu_worker", job]


def settings_for_cpu_job(settings: Settings) -> dict[str, Any]:
    data = settings.model_dump(mode="json")
    data["tavily_api_key"] = None
    data["ocr_cloud_api_key"] = None
    return data


def models_for_cpu_job(models: ModelsConfig) -> dict[str, Any]:
    data = models.model_dump(mode="json")
    for resource in data.get("resources") or []:
        resource["api_key"] = None
    return data


def _env_seconds(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0.05, float(raw))
    except ValueError:
        return default


def _env_seconds_optional(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return max(0.05, float(raw))
    except ValueError:
        return None


def cpu_job_max_seconds(*, file_bytes: int = 0, page_count: int | None = None) -> float:
    """Wall-clock budget: max(30min, pages×60s, MiB×30s), capped at 8h."""
    mb_budget = max(0, int(file_bytes)) / _MIB * CPU_JOB_SECONDS_PER_MIB
    page_budget = 0.0
    if page_count is not None and int(page_count) > 0:
        page_budget = int(page_count) * CPU_JOB_SECONDS_PER_PAGE
    budget = max(mb_budget, page_budget)
    return min(max(CPU_JOB_MAX_FLOOR_SECONDS, budget), CPU_JOB_MAX_CEILING_SECONDS)


def page_count_from_progress(fmt: str, total: int, message: str) -> int | None:
    """PDF/OCR progress totals are pages; TXT char/byte totals must not count."""
    if str(fmt or "").lower() not in PAGE_PROGRESS_FORMATS:
        return None
    if total < 1 or total > CPU_JOB_MAX_PLAUSIBLE_PAGES:
        return None
    msg = message or ""
    if "页" in msg or "PDF" in msg or "OCR" in msg or "扫描" in msg:
        return total
    return None


def probe_pdf_page_count(path: Path) -> int | None:
    try:
        import fitz

        doc = fitz.open(str(path))
        try:
            count = int(doc.page_count)
        finally:
            doc.close()
        return count if count > 0 else None
    except Exception:
        pass
    try:
        from pypdf import PdfReader

        count = len(PdfReader(str(path)).pages)
        return count if count > 0 else None
    except Exception:
        return None


def _job_file_path(job: dict[str, Any]) -> Path | None:
    for key in ("dest", "file_path", "src"):
        raw = job.get(key)
        if not raw:
            continue
        path = Path(str(raw))
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    return None


def job_scale(job: dict[str, Any]) -> tuple[int, int | None]:
    path = _job_file_path(job)
    file_bytes = 0
    if path is not None:
        try:
            file_bytes = int(path.stat().st_size)
        except OSError:
            file_bytes = 0
    page_count: int | None = None
    explicit = job.get("page_count")
    if explicit is not None:
        try:
            parsed = int(explicit)
            if parsed > 0:
                page_count = parsed
        except (TypeError, ValueError):
            page_count = None
    fmt = str(job.get("fmt") or "").lower()
    if page_count is None and fmt == "pdf" and path is not None:
        page_count = probe_pdf_page_count(path)
    return file_bytes, page_count


def _job_max_timeout_message(max_job: float) -> str:
    minutes = max(1, int(round(max_job / 60.0)))
    return f"分段超时：单本处理超过 {minutes} 分钟"


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def run_cpu_worker_sync(
    job: dict[str, Any],
    cancel_event: threading.Event,
    on_progress: ProgressFn | None,
    data_dir: Path,
) -> dict[str, Any]:
    """Spawn ``--cpu-worker`` and stream JSONL progress. Blocks a worker thread."""
    work_dir = Path(data_dir) / "cpu-jobs"
    work_dir.mkdir(parents=True, exist_ok=True)
    job_path = work_dir / f"{job.get('book_id', 'job')}-{job.get('kind', 'cpu')}.json"
    job_path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(job_path, 0o600)
    except OSError:
        pass
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env[CPU_WORKER_ENV] = "1"
    root = str(_package_root())
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(p for p in (root, existing) if p)
    stderr_chunks: list[str] = []
    result: dict[str, Any] | None = None
    env_max = _env_seconds_optional(JOB_MAX_ENV)
    file_bytes, page_count = job_scale(job)
    computed_max = cpu_job_max_seconds(file_bytes=file_bytes, page_count=page_count)
    max_job = [env_max if env_max is not None else computed_max]
    job_max_locked = env_max is not None
    fmt = str(job.get("fmt") or "")
    proc = subprocess.Popen(
        cpu_worker_command(job_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
    )
    last_progress_at = [time.monotonic()]
    last_message = [""]
    timed_out = threading.Event()
    timeout_reason = [""]

    def _drain_stderr() -> None:
        assert proc.stderr is not None
        for chunk in iter(lambda: proc.stderr.read(4096), ""):
            stderr_chunks.append(chunk)

    def _watch_cancel() -> None:
        while proc.poll() is None:
            if cancel_event.is_set():
                proc.kill()
                return
            time.sleep(0.05)

    def _maybe_extend_job_max(total: int, message: str) -> None:
        if job_max_locked:
            return
        pages = page_count_from_progress(fmt, total, message)
        if pages is None:
            return
        extended = cpu_job_max_seconds(file_bytes=file_bytes, page_count=pages)
        if extended > max_job[0]:
            max_job[0] = extended

    def _watch_timeout() -> None:
        stall = _env_seconds(STALL_ENV, CPU_STALL_SECONDS)
        started = time.monotonic()
        while proc.poll() is None:
            if cancel_event.is_set() or timed_out.is_set():
                return
            now = time.monotonic()
            if now - started >= max_job[0]:
                timeout_reason[0] = _job_max_timeout_message(max_job[0])
                timed_out.set()
                proc.kill()
                return
            if now - last_progress_at[0] >= stall:
                stage = last_message[0] or "未知"
                timeout_reason[0] = f"分段超时：超过 3 分钟没有进度（阶段：{stage}）"
                timed_out.set()
                proc.kill()
                return
            time.sleep(0.05)

    stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
    cancel_thread = threading.Thread(target=_watch_cancel, daemon=True)
    timeout_thread = threading.Thread(target=_watch_timeout, daemon=True)
    stderr_thread.start()
    cancel_thread.start()
    timeout_thread.start()
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if cancel_event.is_set() or timed_out.is_set():
                proc.kill()
                break
            stripped = line.strip()
            if not stripped:
                continue
            try:
                msg = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            kind = msg.get("type")
            if kind == "progress":
                last_progress_at[0] = time.monotonic()
                last_message[0] = str(msg.get("message") or "")
                _maybe_extend_job_max(int(msg.get("total") or 0), last_message[0])
                if on_progress is not None:
                    on_progress(
                        int(msg.get("page") or 0),
                        int(msg.get("total") or 0),
                        last_message[0],
                    )
            elif kind == "done":
                last_progress_at[0] = time.monotonic()
                result = msg
            elif kind == "error":
                raise RuntimeError(str(msg.get("message") or "cpu worker failed"))
        proc.wait()
    except Exception:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        raise
    finally:
        stderr_thread.join(timeout=2)
        timeout_thread.join(timeout=2)
        try:
            job_path.unlink(missing_ok=True)
        except OSError:
            pass

    if cancel_event.is_set():
        raise DocumentLoadCancelled("已取消")
    if timed_out.is_set():
        raise RuntimeError(timeout_reason[0] or "分段超时")
    if result is None:
        err = "".join(stderr_chunks).strip()
        code = proc.returncode
        raise RuntimeError(err or f"cpu worker exited {code}")
    return result


def execute_ingest_cpu(job: dict[str, Any]) -> None:
    from lumina_core.jobs.ingest import (
        _chunk_ingest_sync,
        _load_ingest_sync,
        _map_ingest_sync,
        _payload_ingest_sync,
        _persist_ingest_sync,
    )

    settings = Settings.model_validate(job["settings"])
    models = ModelsConfig.model_validate(job["models"])
    cancel_event = threading.Event()

    def on_progress(page: int, total: int, message: str) -> None:
        _emit({"type": "progress", "page": page, "total": total, "message": message})

    dest = Path(str(job["dest"]))
    src = Path(str(job["src"]))
    book_id = str(job["book_id"])
    _emit({"type": "progress", "page": 0, "total": 0, "message": "正在解析文档…"})
    if str(job["fmt"]) == "txt":
        from lumina_core.ingest.txt_persist import persist_streamed_txt_ingest

        count, _meta, _lang = persist_streamed_txt_ingest(
            Path(str(job["db_path"])),
            book_id=book_id,
            dest=dest,
            src=src,
            models=models,
            metadata={},
            target_language=str(job["target_language"]),
            segment_tier=normalize_segment_tier(str(job.get("segment_tier") or "normal")),
            cancel_event=cancel_event,
            on_progress=on_progress,
        )
        _emit({"type": "done", "segment_count": count})
        return
    text, metadata = _load_ingest_sync(
        dest, str(job["fmt"]), settings, on_progress, cancel_event
    )
    _emit(
        {
            "type": "progress",
            "page": 0,
            "total": 0,
            "message": "正在识别序言与正文结构…",
        }
    )
    units = _map_ingest_sync(text, metadata, cancel_event, on_progress)
    _emit(
        {
            "type": "progress",
            "page": 0,
            "total": 0,
            "message": "正在按文档地图切分阅读单元…",
        }
    )
    chunks, _tree, budget = _chunk_ingest_sync(
        text,
        metadata,
        models,
        cancel_event,
        units,
        on_progress,
    )
    segment_tier = normalize_segment_tier(str(job.get("segment_tier") or "normal"))
    segments, ingest_meta, detected_language = _payload_ingest_sync(
        book_id,
        text,
        chunks,
        metadata,
        budget,
        segment_tier,
        cancel_event,
    )
    _emit({"type": "progress", "page": 0, "total": 0, "message": "正在写入书库…"})
    _persist_ingest_sync(
        Path(str(job["db_path"])),
        book_id=book_id,
        src=src,
        metadata=metadata,
        detected_language=detected_language,
        target_language=str(job["target_language"]),
        segments=segments,
        ingest_meta=ingest_meta,
    )
    _emit({"type": "done", "segment_count": len(segments)})


def execute_resegment_cpu(job: dict[str, Any]) -> None:
    from lumina_core.jobs.resegment import (
        _chunk_resegment_sync,
        _extract_document_sync,
        _map_resegment_sync,
        _payload_resegment_sync,
        _persist_resegment_sync,
    )

    settings = Settings.model_validate(job["settings"])
    cancel_event = threading.Event()

    def on_progress(page: int, total: int, message: str) -> None:
        _emit({"type": "progress", "page": page, "total": total, "message": message})

    book_id = str(job["book_id"])
    _emit({"type": "progress", "page": 0, "total": 0, "message": "正在解析文档…"})
    if str(job.get("fmt") or "") == "txt":
        from lumina_core.ingest.txt_persist import persist_streamed_txt_resegment

        count, _meta = persist_streamed_txt_resegment(
            Path(str(job["db_path"])),
            book_id=book_id,
            dest=Path(str(job["file_path"])),
            chunk_target_chars=int(job["chunk_target_chars"]),
            old_metadata=dict(job.get("old_metadata") or {}),
            final_status=str(job["final_status"]),
            segment_tier=normalize_segment_tier(str(job.get("segment_tier") or "normal")),
            cancel_event=cancel_event,
            on_progress=on_progress,
        )
        _emit(
            {
                "type": "done",
                "segment_count": count,
                "chunk_target_chars": int(job["chunk_target_chars"]),
            }
        )
        return
    text, extracted_metadata = _extract_document_sync(
        Path(str(job["file_path"])),
        str(job["fmt"]),
        settings,
        on_progress,
        cancel_event,
    )
    _emit(
        {
            "type": "progress",
            "page": 0,
            "total": 0,
            "message": "正在识别序言与正文结构…",
        }
    )
    units = _map_resegment_sync(text, extracted_metadata, cancel_event, on_progress)
    _emit(
        {
            "type": "progress",
            "page": 0,
            "total": 0,
            "message": "正在按文档地图切分阅读单元…",
        }
    )
    chunks, _tree, _budget = _chunk_resegment_sync(
        text,
        extracted_metadata,
        int(job["chunk_target_chars"]),
        cancel_event,
        units,
        on_progress,
    )
    resolved_tier = normalize_segment_tier(str(job.get("segment_tier") or "normal"))
    segments, metadata = _payload_resegment_sync(
        book_id,
        text,
        chunks,
        dict(job.get("old_metadata") or {}),
        extracted_metadata,
        int(job["chunk_target_chars"]),
        resolved_tier,
        cancel_event,
    )
    _emit({"type": "progress", "page": 0, "total": 0, "message": "正在写入书库…"})
    _persist_resegment_sync(
        Path(str(job["db_path"])),
        book_id,
        segments,
        metadata_json=metadata,
        status=str(job["final_status"]),
    )
    _emit(
        {
            "type": "done",
            "segment_count": len(segments),
            "chunk_target_chars": int(job["chunk_target_chars"]),
        }
    )


def run_cpu_job_file(job_path: Path) -> int:
    os.environ[CPU_WORKER_ENV] = "1"
    try:
        job = json.loads(job_path.read_text(encoding="utf-8"))
        kind = str(job.get("kind") or "")
        if kind == "ingest":
            execute_ingest_cpu(job)
        elif kind == "resegment":
            execute_resegment_cpu(job)
        else:
            raise ValueError(f"unknown cpu job kind: {kind}")
        return 0
    except Exception as exc:
        logger.exception("cpu worker failed")
        try:
            _emit({"type": "error", "message": str(exc)})
        except Exception:
            pass
        return 1


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: python -m lumina_core.jobs.cpu_worker JOB.json", file=sys.stderr)
        return 2
    return run_cpu_job_file(Path(args[0]))


if __name__ == "__main__":
    raise SystemExit(main())
