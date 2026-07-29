"""EPUB parsing via ebooklib — spine → chapters → plain text."""

from __future__ import annotations

import re
from html import unescape
from pathlib import Path


def _html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = re.sub(r"(?i)</h[1-6]>", "\n\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_epub(path: Path) -> tuple[str, dict]:
    try:
        import ebooklib
        from ebooklib import epub
    except ImportError as e:
        raise RuntimeError("EPUB support requires ebooklib: pip install ebooklib") from e

    book = epub.read_epub(str(path))
    title = (book.get_metadata("DC", "title") or [[None]])[0][0]
    author = (book.get_metadata("DC", "creator") or [[None]])[0][0]

    parts: list[str] = []
    skipped_chapters = 0
    seen_hrefs: set[str] = set()

    for spine_entry in book.spine:
        href = spine_entry[0] if isinstance(spine_entry, tuple) else spine_entry
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)

        item = book.get_item_with_href(href)
        if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue

        name = item.get_name() or href
        chapter_title = Path(name).stem.replace("_", " ")
        try:
            raw_html = item.get_content().decode("utf-8", errors="replace")
        except Exception:
            skipped_chapters += 1
            continue

        body = _html_to_text(raw_html)
        if not body:
            skipped_chapters += 1
            continue
        parts.append(f"## [§{chapter_title}]\n{body}")

    metadata: dict = {"title": title, "author": author}
    if skipped_chapters:
        metadata["skipped_chapters"] = skipped_chapters

    return "\n\n".join(parts), metadata
