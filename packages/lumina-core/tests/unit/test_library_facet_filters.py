"""Bookshelf facet filters: 摘要 / 阅读 / 分类 each have 全部 and AND together."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def test_macos_bookshelf_facets_have_all_and_combine():
    core = (ROOT / "apps/macos/Lumina/Services/CoreClient.swift").read_text(
        encoding="utf-8"
    )
    assert "case summaryAll" in core
    assert "case readingAll" in core
    assert "case categoryAll" in core
    assert "summary.matches(book)" in core
    assert "reading.matches(book)" in core
    assert "category.matches(book)" in core
    assert 'return "全部"' in core
    assert "case segmenting" in core
    assert 'return "分段中"' in core
    assert "case ingestFailed" in core
    assert 'return "导入失败"' in core
    assert "case .ingestFailed:" in core
    assert "var isSegmenting" in core
    assert "var summaryFacetLabel" in core
    assert "return book.isSegmenting" in core

    sidebar = (
        ROOT / "apps/macos/Lumina/Features/Library/LibraryCollectionSidebar.swift"
    ).read_text(encoding="utf-8")
    assert "List(selection:" not in sidebar
    assert "selectFacet" in sidebar

    vm = (ROOT / "apps/macos/Lumina/Features/Library/LibraryViewModel.swift").read_text(
        encoding="utf-8"
    )
    assert "query.matches" in vm
    assert "lumina.library.facets" in vm
    assert "setCollection" not in vm
    assert "hasProcessingBooks" in vm
    row = (ROOT / "apps/macos/Lumina/Features/Library/BookRow.swift").read_text(
        encoding="utf-8"
    )
    assert "struct BookSummaryStateBadge" in row


def test_windows_bookshelf_facets_have_all_and_combine():
    models = (ROOT / "apps/windows/Lumina/Services/Models.cs").read_text(
        encoding="utf-8"
    )
    assert "class LibraryFacets" in models
    assert "MatchesSummary" in models
    assert "MatchesReading" in models
    assert "MatchesCategory" in models

    page = (
        ROOT / "apps/windows/Lumina/Features/Library/LibraryPage.xaml.cs"
    ).read_text(encoding="utf-8")
    assert 'AddRadio(LibraryFacets.SummaryGroup, "全部"' in page
    assert 'AddRadio(LibraryFacets.ReadingGroup, "全部"' in page
    assert 'AddRadio(LibraryFacets.CategoryGroup, "全部"' in page
    assert "LibraryFacets.Matches(" in page
    assert "CollectionNav" not in page
    assert 'AddRadio(LibraryFacets.SummaryGroup, "分段中"' in page
    assert 'AddRadio(LibraryFacets.SummaryGroup, "导入失败"' in page
    assert 'Segmenting => "分段中"' in models
    assert 'IngestFailed => "导入失败"' in models
    assert "IsSegmenting" in models
    assert "SummaryFacetLabel" in models
    assert "CanOpenInReader" in models


def test_opening_another_book_is_not_blocked_by_segmenting():
    """分段中 must not swallow shelf clicks or share SSE HTTP slots with openBook."""
    core = (ROOT / "apps/macos/Lumina/Services/CoreClient.swift").read_text(
        encoding="utf-8"
    )
    assert "var canOpenInReader: Bool { !isIngestFailed }" in core
    subscribe = core.split("func subscribeEvents", 1)[1].split("private static let maxConnectionAttempts", 1)[0]
    assert "Self.sseSession.bytes" in subscribe
    assert "session.bytes" not in subscribe

    bookshelf = (
        ROOT / "apps/macos/Lumina/Features/Library/BookshelfView.swift"
    ).read_text(encoding="utf-8")
    assert "if book.isSegmenting { return }" not in bookshelf
    assert "canOpenInReader" in bookshelf

    card = (ROOT / "apps/macos/Lumina/Features/Library/BookCard.swift").read_text(
        encoding="utf-8"
    )
    row = (ROOT / "apps/macos/Lumina/Features/Library/BookRow.swift").read_text(
        encoding="utf-8"
    )
    assert "LibraryIngestMeter" in card
    assert "ProgressView()" not in card
    assert "ProgressView()" not in row

    page = (
        ROOT / "apps/windows/Lumina/Features/Library/LibraryPage.xaml.cs"
    ).read_text(encoding="utf-8")
    assert "if (book.IsSegmenting || book.IsIngestFailed)" not in page
    assert "CanOpenInReader" in page
    assert 'b.Status == "processing"' in page

    win_client = (ROOT / "apps/windows/Lumina/Services/CoreClient.cs").read_text(
        encoding="utf-8"
    )
    assert "_sseHttp" in win_client
    assert "_sseHttp.SendAsync" in win_client
