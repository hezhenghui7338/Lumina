"""Load segment text and build listen scripts without pulling raw_text for summaries."""

from __future__ import annotations

from typing import Any

from lumina_core.db.repos import SegmentRepo
from lumina_core.tts.script import ListenMode, ListenScript, build_listen_script


def load_listen_script(
    repo: SegmentRepo,
    book_id: str,
    idx: int,
    mode: ListenMode,
    *,
    language_hint: str | None = None,
) -> tuple[ListenScript, dict[str, Any] | None]:
    """Return (script, row). Summary modes use get_summary_by_index only."""
    if mode == "original":
        row = repo.get_by_index(book_id, idx)
        if row is None:
            return (
                ListenScript(
                    mode=mode,
                    language=language_hint or "zh",
                    ready=False,
                    skip_reason="missing_segment",
                ),
                None,
            )
        script = build_listen_script(
            mode=mode,
            raw_text=row.get("raw_text") or "",
            language_hint=language_hint,
        )
        return script, row

    row = repo.get_summary_by_index(book_id, idx)
    if row is None:
        return (
            ListenScript(
                mode=mode,
                language=language_hint or "zh",
                ready=False,
                skip_reason="missing_segment",
            ),
            None,
        )
    status = (row.get("summary_status") or "").strip()
    json_blob = row.get("summary_json")
    if status not in ("ready", "done") or not json_blob:
        return (
            ListenScript(
                mode=mode,
                language=language_hint or "zh",
                ready=False,
                skip_reason="summary_not_ready",
            ),
            row,
        )
    script = build_listen_script(
        mode=mode,
        summary_json=json_blob,
        language_hint=language_hint,
    )
    return script, row
