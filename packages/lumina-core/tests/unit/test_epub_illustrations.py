"""EPUB inline illustration extraction and filtering."""

from __future__ import annotations

from lumina_core.chunker.chunker import ChunkSegment
from lumina_core.ingest.html import (
    parse_html_document,
    parse_html_document_with_images,
)
from lumina_core.ingest.illustrations import (
    classify_illustration_role,
    map_illustrations_to_chunks,
    map_illustrations_to_joined_segments,
)


def test_parse_html_with_images_preserves_text():
    html = "<p>Hello <img src='images/fig.png' alt='图' width='400' height='300'> world</p>"
    plain, _ = parse_html_document(html)
    with_images, _, hits = parse_html_document_with_images(html)
    assert with_images == plain == "Hello world"
    assert len(hits) == 1
    assert hits[0]["href"] == "images/fig.png"
    assert hits[0]["offset"] == len("Hello ")


def test_parse_html_skips_remote_and_data_images():
    html = (
        "<p>A<img src='data:image/png;base64,xx'>B"
        "<img src='https://example.com/x.png'>C"
        "<img src='local.png' width='200' height='200'>D</p>"
    )
    text, _, hits = parse_html_document_with_images(html)
    assert "local.png" in {h["href"] for h in hits}
    assert len(hits) == 1
    assert "A" in text and "D" in text


def test_classify_filters_decorative_cover_and_tiny():
    assert (
        classify_illustration_role(
            href="images/cover.jpg",
            alt="",
            class_name="",
            style="",
            epub_type="cover",
            width=800,
            height=1200,
            byte_size=80_000,
            sha256="aaa",
            cover_sha256=None,
        )
        == "cover_dup"
    )
    assert (
        classify_illustration_role(
            href="images/icon_bullet.png",
            alt="",
            class_name="icon",
            style="",
            epub_type="",
            width=32,
            height=32,
            byte_size=400,
            sha256="bbb",
            cover_sha256=None,
        )
        == "decorative"
    )
    assert (
        classify_illustration_role(
            href="images/fig1.png",
            alt="地图",
            class_name="figure",
            style="",
            epub_type="",
            width=600,
            height=400,
            byte_size=40_000,
            sha256="ccc",
            cover_sha256="coverhash",
        )
        == "illustration"
    )
    assert (
        classify_illustration_role(
            href="images/dup.png",
            alt="",
            class_name="",
            style="",
            epub_type="",
            width=600,
            height=400,
            byte_size=40_000,
            sha256="coverhash",
            cover_sha256="coverhash",
        )
        == "cover_dup"
    )


def test_map_illustrations_to_chunks():
    chunks = [
        ChunkSegment(index=0, raw_text="abc", start_offset=0, end_offset=3),
        ChunkSegment(index=1, raw_text="defgh", start_offset=3, end_offset=8),
    ]
    mapped = map_illustrations_to_chunks(
        [{"offset": 4, "href": "a.png"}],
        chunks,
    )
    assert len(mapped) == 1
    assert mapped[0]["segment_idx"] == 1
    assert mapped[0]["char_offset"] == 1


def test_map_illustrations_to_joined_segments_exact():
    segments = [
        {"id": "s0", "idx": 0, "raw_text": "hello "},
        {"id": "s1", "idx": 1, "raw_text": "world"},
    ]
    text = "hello world"
    mapped = map_illustrations_to_joined_segments(
        [{"offset": 6, "href": "fig.png"}],
        extracted_text=text,
        segments=segments,
    )
    assert len(mapped) == 1
    assert mapped[0]["segment_idx"] == 1
    assert mapped[0]["char_offset"] == 0
    assert mapped[0]["segment_id"] == "s1"
