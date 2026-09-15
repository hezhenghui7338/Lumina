"""Book cover extraction for the library grid."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from lumina_core.ingest.cover import (
    extract_cover_image,
    save_book_cover,
    strip_cover_payload,
)

# 1x1 PNG
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
    "0000000c4944415408d763f8cfc00000000300010005fed4ef0000000049454e44ae426082"
)


def _write_epub_with_cover(path: Path, *, via: str = "property") -> None:
    ebooklib = pytest.importorskip("ebooklib")
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("lumina-cover-test")
    book.set_title("带封面")
    book.add_author("测试")

    if via == "set_cover":
        book.set_cover("images/cover.png", _PNG, create_page=False)
        chapter = epub.EpubHtml(
            title="第一章",
            file_name="ch1.xhtml",
            uid="ch1",
            lang="zh",
        )
        chapter.set_content("<html><body><h1>第一章</h1><p>正文。</p></body></html>")
        book.add_item(chapter)
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = [chapter]
        epub.write_epub(str(path), book)
        return

    cover = epub.EpubItem(
        uid="cover-img",
        file_name="images/cover.png",
        media_type="image/png",
        content=_PNG,
    )
    if via == "property":
        cover.properties = ["cover-image"]
    book.add_item(cover)

    chapter = epub.EpubHtml(
        title="第一章",
        file_name="ch1.xhtml",
        uid="ch1",
        lang="zh",
    )
    if via == "homepage":
        chapter.set_content(
            '<html><body><img src="images/cover.png"/><h1>第一章</h1><p>正文。</p></body></html>'
        )
    else:
        chapter.set_content("<html><body><h1>第一章</h1><p>正文。</p></body></html>")
    book.add_item(chapter)

    if via == "guide":
        book.guide = [{"type": "cover", "href": "images/cover.png", "title": "Cover"}]

    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = [chapter]
    epub.write_epub(str(path), book)


def test_extract_epub_cover_via_cover_image_property(tmp_path):
    path = tmp_path / "prop.epub"
    _write_epub_with_cover(path, via="property")
    extracted = extract_cover_image(path, "epub")
    assert extracted is not None
    data, ext = extracted
    assert ext == "png"
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_extract_epub_cover_via_homepage_image(tmp_path):
    path = tmp_path / "home.epub"
    _write_epub_with_cover(path, via="homepage")
    extracted = extract_cover_image(path, "epub")
    assert extracted is not None
    assert extracted[0][:8] == b"\x89PNG\r\n\x1a\n"


def test_extract_epub_cover_via_set_cover(tmp_path):
    path = tmp_path / "set-cover.epub"
    _write_epub_with_cover(path, via="set_cover")
    extracted = extract_cover_image(path, "epub")
    assert extracted is not None
    assert extracted[0][:8] == b"\x89PNG\r\n\x1a\n"


def test_save_book_cover_writes_relative_file(tmp_path):
    path = tmp_path / "book.epub"
    _write_epub_with_cover(path, via="property")
    book_dir = tmp_path / "lib" / "bid"
    rel = save_book_cover(path, book_dir, "epub")
    assert rel == "cover.png"
    assert (book_dir / rel).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_extract_fb2_cover(tmp_path):
    b64 = base64.b64encode(_PNG).decode("ascii")
    fb2 = f"""<?xml version="1.0" encoding="utf-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0"
             xmlns:l="http://www.w3.org/1999/xlink">
  <description>
    <title-info>
      <book-title>FB2 Cover</book-title>
      <coverpage><image l:href="#cover.png"/></coverpage>
    </title-info>
  </description>
  <body>
    <section><p>正文段落。</p></section>
  </body>
  <binary id="cover.png" content-type="image/png">{b64}</binary>
</FictionBook>
"""
    path = tmp_path / "cover.fb2"
    path.write_text(fb2, encoding="utf-8")
    extracted = extract_cover_image(path, "fb2")
    assert extracted is not None
    assert extracted[0] == _PNG
    assert extracted[1] == "png"


def test_strip_cover_payload():
    assert strip_cover_payload({"title": "a", "cover_bytes": b"x"}) == {"title": "a"}


def test_txt_has_no_cover(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("hello", encoding="utf-8")
    assert extract_cover_image(path, "txt") is None
