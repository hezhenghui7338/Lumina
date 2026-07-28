"""Generate chunking live review reports."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from lumina_core.chunker.chunker import ChunkSegment
from lumina_core.summarize.schema import SegmentSummary


def write_chunking_report(
    *,
    fixture_name: str,
    model: str,
    segments: list[ChunkSegment],
    summaries: dict[int, SegmentSummary],
    output_dir: Path,
    duration_seconds: float,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = output_dir / f"chunking_report_{fixture_name}_{ts}.md"

    lines = [
        "# Chunking Live Report",
        "",
        f"- **Fixture**: {fixture_name}",
        f"- **Date**: {datetime.now(timezone.utc).date().isoformat()}",
        f"- **Model**: {model}",
        f"- **Total segments**: {len(segments)}",
        f"- **Duration**: {duration_seconds:.1f}s",
        "",
    ]

    for idx in (0, 1):
        if idx >= len(segments):
            break
        seg = segments[idx]
        summary = summaries.get(idx)
        lines.extend(
            [
                f"## Segment {idx}",
                "",
                f"- **Chars**: {len(seg.raw_text)}",
                f"- **Chapter**: {seg.chapter or '—'}",
                f"- **Offset**: {seg.start_offset}–{seg.end_offset}",
            ]
        )
        if summary:
            lines.extend(
                [
                    f"- **Label**: 「{summary.label}」",
                    f"- **Anchor**: {summary.anchor}",
                    "- **Summary sentences**:",
                    *[f"  {i + 1}. {s}" for i, s in enumerate(summary.sentences)],
                    "- **Bullets**:",
                    *[f"  - {b}" for b in summary.bullets],
                ]
            )
        preview = seg.raw_text[:200].replace("\n", " ")
        lines.extend(["", f"- **Preview**: {preview}…", ""])

    if len(segments) >= 2:
        lines.extend(
            [
                "## Boundary check",
                "",
                f"- Segment 0 ends at: {segments[0].end_offset}",
                f"- Segment 1 starts at: {segments[1].start_offset}",
                f"- Overlap: {'yes' if segments[0].end_offset > segments[1].start_offset else 'none'}",
                "",
            ]
        )

    lines.extend(
        [
            "## Review checklist",
            "",
            "- [ ] S1 段 0/1 边界合理",
            "- [ ] S2 摘要准确、无串台",
            "- [ ] S3 label 可用于段列表导航",
            "- [ ] S4 古文/网文特殊场景 OK（如适用）",
            "",
            "## Sign-off",
            "",
            "- **Reviewer**: _pending_",
            "- **Result**: PASS / FAIL / PASS with notes",
            "- **Notes**:",
            "",
        ]
    )

    path.write_text("\n".join(lines), encoding="utf-8")
    return path
