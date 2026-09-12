import XCTest
@testable import Lumina

@MainActor
final class LibraryViewModelMergeTests: XCTestCase {
    private func book(
        id: String,
        title: String = "Book",
        status: String = "reading",
        segmentCount: Int? = 10,
        summaryReady: Int? = nil,
        summaryTotal: Int? = nil,
        summarizeState: String? = nil,
        lastOpenedAt: String? = nil,
        currentSegmentIndex: Int? = nil,
        isFavorite: Bool? = nil,
        category: String? = nil,
        createdAt: String? = nil,
        readingPercent: Double? = nil
    ) -> BookSummary {
        BookSummary(
            id: id,
            title: title,
            status: status,
            segment_count: segmentCount,
            is_favorite: isFavorite,
            category: category,
            last_opened_at: lastOpenedAt,
            current_segment_index: currentSegmentIndex,
            created_at: createdAt,
            summary_ready_count: summaryReady,
            summary_total_count: summaryTotal,
            summarize_state: summarizeState,
            readingPercent: readingPercent
        )
    }

    func testMergePreservingOrder_keepsOrderAndUpdatesFields() {
        let existing = [
            book(id: "a", title: "Alpha", summaryReady: 1, summaryTotal: 5),
            book(id: "b", title: "Beta", summaryReady: 2, summaryTotal: 5),
            book(id: "c", title: "Gamma", summaryReady: 3, summaryTotal: 5),
        ]
        let fetched = [
            book(id: "c", title: "Gamma", summaryReady: 5, summaryTotal: 5),
            book(id: "a", title: "Alpha", summaryReady: 4, summaryTotal: 5),
            book(id: "b", title: "Beta", summaryReady: 3, summaryTotal: 5),
        ]

        let merged = LibraryViewModel.mergePreservingOrder(existing: existing, fetched: fetched)

        XCTAssertEqual(merged.map(\.id), ["a", "b", "c"])
        XCTAssertEqual(merged[0].summaryReady, 4)
        XCTAssertEqual(merged[1].summaryReady, 3)
        XCTAssertEqual(merged[2].summaryReady, 5)
    }

    func testMergePreservingOrder_removesBooksNoLongerInCollection() {
        let existing = [
            book(id: "a"),
            book(id: "b"),
            book(id: "c"),
        ]
        let fetched = [
            book(id: "c"),
            book(id: "a"),
        ]

        let merged = LibraryViewModel.mergePreservingOrder(existing: existing, fetched: fetched)

        XCTAssertEqual(merged.map(\.id), ["a", "c"])
    }

    func testMergePreservingOrder_appendsNewBooksAtEnd() {
        let existing = [
            book(id: "a"),
            book(id: "b"),
        ]
        let fetched = [
            book(id: "c"),
            book(id: "a"),
            book(id: "b"),
        ]

        let merged = LibraryViewModel.mergePreservingOrder(existing: existing, fetched: fetched)

        XCTAssertEqual(merged.map(\.id), ["a", "b", "c"])
    }

    func testPrioritizeSummarizeActivity_runningThenQueuedThenRest() {
        let books = [
            book(id: "idle", summarizeState: "idle"),
            book(id: "running", summarizeState: "running"),
            book(id: "recent", lastOpenedAt: "2024-05-01T00:00:00Z"),
            book(id: "queued", summarizeState: "queued"),
        ]

        let prioritized = LibraryViewModel.prioritizeSummarizeActivity(books)

        XCTAssertEqual(prioritized.map(\.id), ["running", "queued", "idle", "recent"])
    }

    /// `displayedBooks` sorts by recency first and only then lifts summarize
    /// activity, so the books that are neither running nor queued must stay in
    /// recency order — not in the order they happened to arrive in.
    func testDisplayedBooks_prioritizesSummarizeActivityWhenRecent() {
        let viewModel = LibraryViewModel()
        viewModel.sort = .recent
        viewModel.books = [
            book(id: "idle", summarizeState: "idle", lastOpenedAt: "2024-01-01T00:00:00Z"),
            book(id: "running", summarizeState: "running", lastOpenedAt: "2024-02-01T00:00:00Z"),
            book(id: "recent", lastOpenedAt: "2024-05-01T00:00:00Z"),
            book(id: "queued", summarizeState: "queued", lastOpenedAt: "2024-03-01T00:00:00Z"),
        ]

        // Recency alone would be recent, queued, running, idle.
        XCTAssertEqual(viewModel.displayedBooks.map(\.id), ["running", "queued", "recent", "idle"])
    }

    func testSummarizingCollectionIncludesQueuedBooks() {
        let viewModel = LibraryViewModel()
        viewModel.query.summary = .summarizing
        viewModel.books = [
            book(id: "running", summarizeState: "running"),
            book(id: "queued", summarizeState: "queued"),
            book(id: "idle", summarizeState: "idle"),
        ]

        XCTAssertEqual(viewModel.displayedBooks.map(\.id), ["running", "queued"])
    }

    func testSegmentingCollectionIncludesProcessingBooks() {
        let viewModel = LibraryViewModel()
        viewModel.query.summary = .segmenting
        viewModel.books = [
            book(id: "importing", status: "processing", segmentCount: 0, summarizeState: "segmenting"),
            book(id: "resegment", status: "processing", summarizeState: "segmenting"),
            book(id: "idle", summarizeState: "idle"),
            book(id: "running", summarizeState: "running"),
            book(
                id: "was-done",
                status: "processing",
                summaryReady: 10,
                summaryTotal: 10,
                summarizeState: "segmenting"
            ),
        ]

        XCTAssertEqual(
            Set(viewModel.displayedBooks.map(\.id)),
            ["importing", "resegment", "was-done"]
        )
        viewModel.query.summary = .summarized
        XCTAssertFalse(viewModel.displayedBooks.map(\.id).contains("was-done"))
        viewModel.query.summary = .idle
        XCTAssertEqual(viewModel.displayedBooks.map(\.id), ["idle"])
    }

    func testEmptyUnreadBookIsSegmentingNotSummarized() {
        let viewModel = LibraryViewModel()
        let hole = book(
            id: "hole",
            status: "unread",
            segmentCount: 0,
            summaryReady: 0,
            summaryTotal: 0,
            summarizeState: "summarized"
        )
        let idle = book(id: "idle", status: "unread", summarizeState: "idle")
        viewModel.books = [hole, idle]

        XCTAssertEqual(hole.summaryFacetLabel, "分段中")
        XCTAssertTrue(hole.isSegmenting)
        XCTAssertTrue(hole.canOpenInReader)
        XCTAssertFalse(hole.hasCompletedSummary)

        viewModel.query.summary = .segmenting
        XCTAssertEqual(viewModel.displayedBooks.map(\.id), ["hole"])
        viewModel.query.summary = .idle
        XCTAssertEqual(viewModel.displayedBooks.map(\.id), ["idle"])
        viewModel.query.summary = .summarized
        XCTAssertFalse(viewModel.displayedBooks.map(\.id).contains("hole"))
        viewModel.query.summary = .ingestFailed
        XCTAssertTrue(viewModel.displayedBooks.isEmpty)
    }

    func testDisplayedBooks_doesNotReorderForTitleSort() {
        let viewModel = LibraryViewModel()
        viewModel.sort = .title
        viewModel.sortOrder = .ascending
        viewModel.books = [
            book(id: "idle", title: "Idle", summarizeState: "idle"),
            book(id: "running", title: "Running", summarizeState: "running"),
            book(id: "queued", title: "Queued", summarizeState: "queued"),
        ]

        XCTAssertEqual(viewModel.displayedBooks.map(\.id), ["idle", "queued", "running"])
    }

    func testReadingCollectionsIgnoreSummarizedStatus() {
        let viewModel = LibraryViewModel()
        viewModel.books = [
            book(id: "unread", lastOpenedAt: nil, currentSegmentIndex: 0),
            book(
                id: "reading",
                lastOpenedAt: "2024-05-01T00:00:00Z",
                currentSegmentIndex: 2
            ),
            book(
                id: "finished",
                lastOpenedAt: "2024-06-01T00:00:00Z",
                currentSegmentIndex: 9,
                readingPercent: 1.0
            ),
            book(
                id: "short",
                segmentCount: 1,
                lastOpenedAt: "2024-07-01T00:00:00Z",
                currentSegmentIndex: 0
            ),
        ]

        viewModel.query.reading = .unread
        XCTAssertEqual(viewModel.displayedBooks.map(\.id), ["unread"])
        viewModel.query.reading = .reading
        XCTAssertEqual(Set(viewModel.displayedBooks.map(\.id)), ["reading", "short"])
        viewModel.query.reading = .finished
        XCTAssertEqual(viewModel.displayedBooks.map(\.id), ["finished"])
    }

    func testApplyReadingProgress_updatesLabelWithoutMarkingFinishedEarly() {
        let viewModel = LibraryViewModel()
        viewModel.books = [
            book(
                id: "reading",
                lastOpenedAt: "2024-05-01T00:00:00Z",
                currentSegmentIndex: 1
            )
        ]

        viewModel.applyLocalProgress(["reading": ReadingPosition(index: 4, total: 10)])

        XCTAssertEqual(viewModel.books[0].current_segment_index, 4)
        XCTAssertEqual(viewModel.books[0].readingStatusLabel, "在读 · 5/10 段")
        XCTAssertEqual(viewModel.books[0].readingProgressBucket, .reading)

        viewModel.applyLocalProgress(["reading": ReadingPosition(index: 9, total: 10)])
        XCTAssertEqual(viewModel.books[0].readingStatusLabel, "已读完")
        XCTAssertEqual(viewModel.books[0].readingProgressBucket, .finished)
    }

    /// The shelf must show what the reader actually recorded, for every book,
    /// not just the one that was open last.
    func testApplyLocalProgress_updatesEveryBookFromTheStore() {
        let viewModel = LibraryViewModel()
        viewModel.books = [
            book(id: "a", lastOpenedAt: "2024-05-01T00:00:00Z", currentSegmentIndex: 0),
            book(id: "b", lastOpenedAt: "2024-05-01T00:00:00Z", currentSegmentIndex: 0),
        ]

        viewModel.applyLocalProgress([
            "a": ReadingPosition(index: 5, total: 10),
            "b": ReadingPosition(index: 8, total: 10),
        ])

        XCTAssertEqual(viewModel.books[0].readingStatusLabel, "在读 · 6/10 段")
        XCTAssertEqual(viewModel.books[1].readingStatusLabel, "在读 · 9/10 段")
    }

    func testApplyReadingProgress_setsOpenedAtWhenUnread() {
        let viewModel = LibraryViewModel()
        viewModel.books = [book(id: "unread", lastOpenedAt: nil, currentSegmentIndex: 0)]

        let opened = Date(timeIntervalSince1970: 1_700_000_000)
        viewModel.applyLocalProgress(
            ["unread": ReadingPosition(index: 2, total: 10)],
            openedAt: opened
        )

        XCTAssertNotNil(viewModel.books[0].last_opened_at)
        XCTAssertEqual(viewModel.books[0].current_segment_index, 2)
        XCTAssertEqual(viewModel.books[0].readingProgressBucket, .reading)
    }

    func testOverlayLocalProgress_prefersCacheWhenSegmentCountMatches() {
        let books = [
            book(id: "a", segmentCount: 10, currentSegmentIndex: 0),
            book(id: "b", segmentCount: 10, currentSegmentIndex: 1),
        ]
        let overlaid = LibraryViewModel.overlayLocalProgress(books) { id in
            id == "a" ? ReadingPosition(index: 6, total: 10) : nil
        }
        XCTAssertEqual(overlaid[0].current_segment_index, 6)
        XCTAssertEqual(overlaid[0].readingPercent, 0.6)
        XCTAssertEqual(overlaid[1].current_segment_index, 1)
    }

    func testOverlayLocalProgress_usesCachedIndexForOpenedBookLabel() {
        let books = [
            book(
                id: "a",
                segmentCount: 10,
                lastOpenedAt: "2024-05-01T00:00:00Z",
                currentSegmentIndex: 0
            )
        ]
        let overlaid = LibraryViewModel.overlayLocalProgress(books) { _ in
            ReadingPosition(index: 4, total: 10)
        }
        XCTAssertEqual(overlaid[0].readingStatusLabel, "在读 · 5/10 段")
        XCTAssertEqual(overlaid[0].readingProgressBucket, .reading)
    }

    func testOverlayLocalProgress_ignoresCacheAfterResegment() {
        let books = [book(id: "a", segmentCount: 4, currentSegmentIndex: 0)]
        let overlaid = LibraryViewModel.overlayLocalProgress(books) { _ in
            ReadingPosition(index: 9, total: 12)
        }
        XCTAssertEqual(overlaid[0].current_segment_index, 0)
    }

    func testSortBySegmentCountDescending() {
        let viewModel = LibraryViewModel()
        viewModel.sort = .segments
        viewModel.books = [
            book(id: "short", title: "Short", segmentCount: 3),
            book(id: "long", title: "Long", segmentCount: 40),
            book(id: "mid", title: "Mid", segmentCount: 12),
        ]

        XCTAssertEqual(viewModel.displayedBooks.map(\.id), ["long", "mid", "short"])
    }

    func testSortByReadingProgressDescending() {
        let viewModel = LibraryViewModel()
        viewModel.sort = .progress
        viewModel.books = [
            book(id: "unread", title: "Unread", lastOpenedAt: nil, currentSegmentIndex: 0),
            book(
                id: "mid",
                title: "Mid",
                lastOpenedAt: "2024-05-01T00:00:00Z",
                currentSegmentIndex: 4
            ),
            book(
                id: "done",
                title: "Finished",
                lastOpenedAt: "2024-06-01T00:00:00Z",
                currentSegmentIndex: 9,
                readingPercent: 1.0
            ),
            book(
                id: "low",
                title: "Low",
                lastOpenedAt: "2024-04-01T00:00:00Z",
                currentSegmentIndex: 1
            ),
            book(
                id: "stale",
                title: "StaleUnread",
                lastOpenedAt: nil,
                currentSegmentIndex: 7
            ),
        ]

        XCTAssertEqual(
            viewModel.displayedBooks.map(\.id),
            ["done", "mid", "low", "stale", "unread"]
        )
    }

    func testSortOrderAscendingReversesDefaultDirection() {
        let books = [
            book(id: "short", title: "Short", segmentCount: 3, isFavorite: false),
            book(id: "long", title: "Long", segmentCount: 40, isFavorite: true),
            book(id: "mid", title: "Mid", segmentCount: 12, isFavorite: false),
        ]
        XCTAssertEqual(
            LibraryViewModel.sorted(books, by: .segments, order: .ascending).map(\.id),
            ["short", "mid", "long"]
        )
        XCTAssertEqual(
            LibraryViewModel.sorted(books, by: .title, order: .descending).map(\.id),
            ["short", "mid", "long"]
        )
        XCTAssertEqual(
            LibraryViewModel.sorted(books, by: .favorite, order: .ascending).map(\.id),
            ["mid", "short", "long"]
        )
        XCTAssertEqual(
            LibraryViewModel.sorted(books, by: .favorite, order: .descending).map(\.id),
            ["long", "short", "mid"]
        )
    }

    func testTitleDefaultOrderIsAscendingOthersDescending() {
        XCTAssertEqual(LibrarySort.title.defaultOrder, .ascending)
        XCTAssertEqual(LibrarySort.recent.defaultOrder, .descending)
        XCTAssertEqual(LibrarySort.segments.defaultOrder, .descending)
        XCTAssertEqual(LibrarySort.favorite.defaultOrder, .descending)
    }

    func testRecentAscendingStillPinsSummarizeActivity() {
        let viewModel = LibraryViewModel()
        viewModel.sort = .recent
        viewModel.sortOrder = .ascending
        viewModel.books = [
            book(id: "idle", summarizeState: "idle", lastOpenedAt: "2024-01-01T00:00:00Z"),
            book(id: "running", summarizeState: "running", lastOpenedAt: "2024-02-01T00:00:00Z"),
            book(id: "recent", lastOpenedAt: "2024-05-01T00:00:00Z"),
            book(id: "queued", summarizeState: "queued", lastOpenedAt: "2024-03-01T00:00:00Z"),
        ]

        // Recency ascending: idle, running, queued, recent; then pin running/queued.
        XCTAssertEqual(viewModel.displayedBooks.map(\.id), ["running", "queued", "idle", "recent"])
    }

    func testTitleQueryFiltersDisplayedBooks() {
        let viewModel = LibraryViewModel()
        viewModel.books = [
            book(id: "a", title: "史记"),
            book(id: "b", title: "黑客与画家"),
        ]
        viewModel.titleQuery = "黑客"
        XCTAssertEqual(viewModel.displayedBooks.map(\.id), ["b"])
    }

    func testFromLegacyCollectionRestoresUnreadReadingAndCategory() {
        XCTAssertEqual(LibraryFacetQuery.fromLegacyCollection("unread").reading, .unread)
        XCTAssertEqual(LibraryFacetQuery.fromLegacyCollection("reading").reading, .reading)
        XCTAssertTrue(LibraryFacetQuery.fromLegacyCollection("all").isDefault)
        XCTAssertTrue(LibraryFacetQuery.fromLegacyCollection("recent").isDefault)
        XCTAssertEqual(LibraryFacetQuery.fromLegacyCollection("文学").category, .category("文学"))
        XCTAssertEqual(LibraryFacetQuery.fromLegacyCollection("summarized").summary, .summarized)
        XCTAssertEqual(LibraryFacetQuery.fromLegacyCollection("segmenting").summary, .segmenting)
        XCTAssertEqual(LibraryFacetQuery.fromLegacyCollection("error").summary, .ingestFailed)
    }

    func testIngestFailedCollectionIsFindableAndExcludedFromOtherSummaryFacets() {
        let viewModel = LibraryViewModel()
        let failed = book(
            id: "fail",
            title: "坏书",
            status: "error",
            segmentCount: 0,
            summarizeState: "summarized"
        )
        let cancelled = book(
            id: "cancel",
            title: "取消",
            status: "error",
            segmentCount: 0,
            summarizeState: "idle"
        )
        let idle = book(
            id: "idle",
            status: "unread",
            summarizeState: "idle"
        )
        let summarized = book(
            id: "done",
            status: "summarized",
            summaryReady: 10,
            summaryTotal: 10,
            summarizeState: "summarized"
        )
        viewModel.books = [failed, cancelled, idle, summarized]

        XCTAssertTrue(viewModel.query.isDefault)
        XCTAssertEqual(Set(viewModel.displayedBooks.map(\.id)), ["fail", "cancel", "idle", "done"])

        viewModel.selectFacet(.ingestFailed)
        XCTAssertEqual(viewModel.query.title, "导入失败")
        XCTAssertEqual(Set(viewModel.displayedBooks.map(\.id)), ["fail", "cancel"])
        XCTAssertEqual(viewModel.count(for: .ingestFailed), 2)

        viewModel.selectFacet(.idle)
        XCTAssertEqual(viewModel.displayedBooks.map(\.id), ["idle"])

        viewModel.selectFacet(.summarized)
        XCTAssertEqual(viewModel.displayedBooks.map(\.id), ["done"])

        viewModel.selectFacet(.summaryAll)
        XCTAssertEqual(Set(viewModel.displayedBooks.map(\.id)), ["fail", "cancel", "idle", "done"])
    }

    func testDefaultFacetsAreAllAndCombineWithAND() {
        let viewModel = LibraryViewModel()
        XCTAssertTrue(viewModel.query.isDefault)
        XCTAssertEqual(viewModel.query.title, "书架")
        viewModel.books = [
            book(
                id: "hit",
                title: "史记",
                summarizeState: "summarized",
                lastOpenedAt: nil,
                currentSegmentIndex: 0,
                category: "历史"
            ),
            book(
                id: "wrong-category",
                title: "黑客与画家",
                summarizeState: "summarized",
                lastOpenedAt: nil,
                currentSegmentIndex: 0,
                category: "科技"
            ),
            book(
                id: "wrong-summary",
                title: "未摘要的史书",
                summarizeState: "idle",
                lastOpenedAt: nil,
                currentSegmentIndex: 0,
                category: "历史"
            ),
            book(
                id: "opened",
                title: "在读的史书",
                summarizeState: "summarized",
                lastOpenedAt: "2024-05-01T00:00:00Z",
                currentSegmentIndex: 2,
                category: "历史"
            ),
        ]

        viewModel.selectFacet(.summarized)
        viewModel.selectFacet(.unread)
        viewModel.selectFacet(.category("历史"))

        XCTAssertEqual(viewModel.displayedBooks.map(\.id), ["hit"])
        XCTAssertEqual(viewModel.query.title, "已摘要 · 未读 · 历史")
        XCTAssertEqual(viewModel.query.summary, .summarized)
        XCTAssertEqual(viewModel.query.reading, .unread)
        XCTAssertEqual(viewModel.query.category, .category("历史"))
    }

    func testSelectFacetKeepsOtherDimensions() {
        var query = LibraryFacetQuery()
        query.apply(.summarized)
        query.apply(.unread)
        query.apply(.summaryAll)
        XCTAssertEqual(query.summary, .summaryAll)
        XCTAssertEqual(query.reading, .unread)
        XCTAssertEqual(query.category, .categoryAll)
    }

    func testFacetedCountRespectsOtherFilters() {
        let viewModel = LibraryViewModel()
        viewModel.books = [
            book(
                id: "history-unread-summarized",
                summarizeState: "summarized",
                lastOpenedAt: nil,
                category: "历史"
            ),
            book(
                id: "history-unread-idle",
                summarizeState: "idle",
                lastOpenedAt: nil,
                category: "历史"
            ),
            book(
                id: "tech-unread-summarized",
                summarizeState: "summarized",
                lastOpenedAt: nil,
                category: "科技"
            ),
        ]
        viewModel.selectFacet(.summarized)
        XCTAssertEqual(viewModel.count(for: .unread), 2)
        viewModel.selectFacet(.category("历史"))
        XCTAssertEqual(viewModel.count(for: .unread), 1)
        XCTAssertEqual(viewModel.count(for: .summaryAll), 2)
        XCTAssertEqual(viewModel.count(for: .categoryAll), 2)
    }

    func testSidebarItemsLeadEachSectionWithAll() {
        let items = LibraryCollection.sidebarItems(categories: ["历史"])
        XCTAssertEqual(items.first { $0.section == .summary }, .summaryAll)
        XCTAssertEqual(items.first { $0.section == .reading }, .readingAll)
        XCTAssertEqual(items.first { $0.section == .category }, .categoryAll)
        XCTAssertTrue(items.contains(.idle))
        XCTAssertTrue(items.contains(.segmenting))
        XCTAssertTrue(items.contains(.ingestFailed))
        XCTAssertTrue(items.contains(.unread))
        XCTAssertTrue(items.contains(.category("历史")))
    }

    func testFacetQueryCodableRoundTrip() throws {
        var query = LibraryFacetQuery(
            summary: .summarized,
            reading: .unread,
            category: .category("历史"),
            favoriteOnly: true
        )
        let data = try JSONEncoder().encode(query)
        let decoded = try JSONDecoder().decode(LibraryFacetQuery.self, from: data)
        XCTAssertEqual(decoded, query)
        query.apply(.favorite)
        XCTAssertFalse(query.favoriteOnly)
    }

    func testIngestProgressLabel_includesPercentWhenTotalKnown() {
        let progress = IngestProgress(page: 25, total: 100, message: "正在按窗口切分阅读单元…")
        XCTAssertEqual(progress.label, "正在按窗口切分阅读单元… · 25%")
        let spinning = IngestProgress(page: 0, total: 0, message: "排队等待分段…")
        XCTAssertEqual(spinning.label, "排队等待分段…")
    }

    func testBookshelfPaging_pageCountAndSlice() {
        XCTAssertEqual(BookshelfPaging.defaultPageSize, 10)
        XCTAssertEqual(BookshelfPaging.allowedPageSizes, [10, 20, 50, 100])
        XCTAssertEqual(BookshelfPaging.normalizedPageSize(10), 10)
        XCTAssertEqual(BookshelfPaging.normalizedPageSize(48), 10)
        XCTAssertEqual(BookshelfPaging.pageCount(total: 0, pageSize: 10), 0)
        XCTAssertEqual(BookshelfPaging.pageCount(total: 10, pageSize: 10), 1)
        XCTAssertEqual(BookshelfPaging.pageCount(total: 11, pageSize: 10), 2)
        XCTAssertEqual(BookshelfPaging.pageCount(total: 100, pageSize: 50), 2)

        let items = Array(0..<100)
        XCTAssertEqual(BookshelfPaging.slice(items, pageIndex: 0, pageSize: 10), Array(0..<10))
        XCTAssertEqual(BookshelfPaging.slice(items, pageIndex: 1, pageSize: 10), Array(10..<20))
        XCTAssertEqual(BookshelfPaging.slice(items, pageIndex: 9, pageSize: 10), Array(90..<100))
        XCTAssertEqual(
            BookshelfPaging.slice(items, pageIndex: 99, pageSize: 10),
            Array(90..<100),
            "out-of-range page clamps to last"
        )
        XCTAssertEqual(BookshelfPaging.clampedPageIndex(-1, pageCount: 3), 0)
        XCTAssertEqual(BookshelfPaging.clampedPageIndex(3, pageCount: 3), 2)
        XCTAssertEqual(BookshelfPaging.clampedPageIndex(0, pageCount: 0), 0)
    }

    func testPagedBooks_slicesMatchedAndResetsOnFacetChange() {
        let viewModel = LibraryViewModel()
        viewModel.pageSize = 10
        viewModel.sort = .title
        viewModel.sortOrder = .ascending
        viewModel.books = (0..<25).map { index in
            book(id: String(format: "%02d", index), title: String(format: "Book %02d", index))
        }

        XCTAssertEqual(viewModel.matchedBooks.count, 25)
        XCTAssertEqual(viewModel.pageCount, 3)
        XCTAssertTrue(viewModel.showsPagination)
        XCTAssertEqual(viewModel.pagedBooks.map(\.id), (0..<10).map { String(format: "%02d", $0) })

        viewModel.setPage(2)
        XCTAssertEqual(viewModel.pageIndex, 2)
        XCTAssertEqual(viewModel.pagedBooks.map(\.id), ["20", "21", "22", "23", "24"])

        viewModel.setPage(99)
        XCTAssertEqual(viewModel.pageIndex, 2)

        viewModel.selectFacet(.unread)
        XCTAssertEqual(viewModel.pageIndex, 0)
    }

    func testSetSortResetsPageIndex() {
        let viewModel = LibraryViewModel()
        viewModel.pageSize = 5
        viewModel.books = (0..<12).map { book(id: "\($0)", title: "T\($0)") }
        viewModel.setPage(1)
        XCTAssertEqual(viewModel.pageIndex, 1)
        viewModel.setSort(.title)
        XCTAssertEqual(viewModel.pageIndex, 0)
    }

    func testSetPageSize_resetsPageAndNormalizes() {
        let viewModel = LibraryViewModel()
        viewModel.books = (0..<30).map { book(id: "\($0)", title: "T\($0)") }
        viewModel.setPageSize(10)
        viewModel.setPage(2)
        XCTAssertEqual(viewModel.pageIndex, 2)

        viewModel.setPageSize(20)
        XCTAssertEqual(viewModel.pageSize, 20)
        XCTAssertEqual(viewModel.pageIndex, 0)
        XCTAssertEqual(viewModel.pageCount, 2)

        viewModel.setPageSize(48)
        XCTAssertEqual(viewModel.pageSize, 10)
        XCTAssertEqual(viewModel.pageIndex, 0)
    }

    func testShowsPagination_whenMatchedBooksExistEvenIfSinglePage() {
        let viewModel = LibraryViewModel()
        viewModel.pageSize = 100
        viewModel.books = [book(id: "1", title: "Only")]
        XCTAssertTrue(viewModel.showsPagination)
        viewModel.books = []
        XCTAssertFalse(viewModel.showsPagination)
    }
}
