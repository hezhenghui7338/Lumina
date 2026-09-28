#!/usr/bin/env python3
"""Rebuild EPUB outline (heading_path/chapter) without whole-book resegment.

Examples:
  uv run python scripts/rebuild-epub-outline.py --title-contains 曾国藩
  uv run python scripts/rebuild-epub-outline.py --book-id <uuid>
  uv run python scripts/rebuild-epub-outline.py --book-id <uuid> --realign-markers
  uv run python scripts/rebuild-epub-outline.py --title-contains 曾国藩 --dry-run
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

# Allow running from repo root without install.
_ROOT = Path(__file__).resolve().parents[1]
_CORE = _ROOT / "packages" / "lumina-core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from lumina_core.db.connection import attach_db_lock  # noqa: E402
from lumina_core.jobs.outline_rebuild import (  # noqa: E402
    find_books_by_title,
    realign_volume_markers_for_book,
    rebuild_outline_for_book,
)


def _default_db() -> Path:
    home = Path.home()
    mac = home / "Library" / "Application Support" / "Lumina" / "lumina.db"
    if mac.is_file():
        return mac
    return home / ".local" / "share" / "Lumina" / "lumina.db"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Path to lumina.db (default: macOS Application Support)",
    )
    parser.add_argument("--book-id", type=str, default=None)
    parser.add_argument("--title-contains", type=str, default=None)
    parser.add_argument(
        "--epub",
        type=Path,
        default=None,
        help="Override EPUB path (default: books.file_path)",
    )
    parser.add_argument(
        "--no-heuristic",
        action="store_true",
        help="Only use EPUB TOC matching (no year/collection nesting fallback)",
    )
    parser.add_argument(
        "--realign-markers",
        action="store_true",
        help=(
            "Split mid-segment # [§曾国藩全集N] onto new segment starts, "
            "then lock volume ranges to those positions"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List matching books only; do not write",
    )
    args = parser.parse_args()

    if not args.book_id and not args.title_contains:
        parser.error("provide --book-id or --title-contains")

    db_path = args.db or _default_db()
    if not db_path.is_file():
        print(f"database not found: {db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    attach_db_lock(conn)

    books = []
    if args.book_id:
        row = conn.execute(
            "SELECT id, title, format, file_path, segment_count FROM books WHERE id = ?",
            (args.book_id,),
        ).fetchone()
        if row is None:
            print(f"book not found: {args.book_id}", file=sys.stderr)
            return 1
        books = [dict(row)]
    else:
        books = find_books_by_title(conn, title_contains=args.title_contains or "")
        if not books:
            print(f"no books matching title contains {args.title_contains!r}", file=sys.stderr)
            return 1

    for book in books:
        print(
            f"book {book['id']}: {book['title']} "
            f"({book.get('format')}, segments={book.get('segment_count')})"
        )
        if args.dry_run:
            continue
        if args.realign_markers:
            realign = realign_volume_markers_for_book(
                conn, book["id"], epub_path=args.epub
            )
            result = realign.outline
            print(
                f"  splits={realign.splits} resummarize={realign.resummarize_indices}"
            )
            print(
                f"  mode={result.mode} toc={result.toc_entries} "
                f"updated={result.updated} unchanged={result.unchanged} "
                f"unmatched={result.unmatched} / {result.segment_count}"
            )
            print(
                "  note: call POST /books/{id}/outline/rebuild"
                "?realign_markers=true to also enqueue summaries via the engine,"
                " or POST summarize/start after this script."
            )
        else:
            result = rebuild_outline_for_book(
                conn,
                book["id"],
                epub_path=args.epub,
                use_heuristic=not args.no_heuristic,
            )
            print(
                f"  mode={result.mode} toc={result.toc_entries} "
                f"updated={result.updated} unchanged={result.unchanged} "
                f"unmatched={result.unmatched} / {result.segment_count}"
            )

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
