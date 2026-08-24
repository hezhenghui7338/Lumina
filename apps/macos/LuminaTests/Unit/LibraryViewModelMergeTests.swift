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

    func testDisplayedBooks_prioritizesSummarizeActivityWhenRecent() {
        let viewModel = LibraryViewModel()
        viewModel.sort = .recent
        viewModel.collection = .recent
        viewModel.books = [
            book(id: "idle", summarizeState: "idle"),
            book(id: "running", summarizeState: "running"),
            book(id: "recent", lastOpenedAt: "2024-05-01T00:00:00Z"),
            book(id: "queued", summarizeState: "queued"),
        ]

        XCTAssertEqual(viewModel.displayedBooks.map(\.id), ["running", "queued", "idle", "recent"])
    }

    func testSummarizingCollectionIncludesQueuedBooks() {
        let viewModel = LibraryViewModel()
        viewModel.collection = .summarizing
        viewModel.books = [
            book(id: "running", summarizeState: "running"),
            book(id: "queued", summarizeState: "queued"),
            book(id: "idle", summarizeState: "idle"),
        ]

        XCTAssertEqual(viewModel.displayedBooks.map(\.id), ["running", "queued"])
    }

    func testDisplayedBooks_doesNotReorderForTitleSort() {
        let viewModel = LibraryViewModel()
        viewModel.sort = .title
        viewModel.collection = .recent
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

        viewModel.collection = .unread
        XCTAssertEqual(viewModel.displayedBooks.map(\.id), ["unread"])
        viewModel.collection = .reading
        XCTAssertEqual(Set(viewModel.displayedBooks.map(\.id)), ["reading", "short"])
        viewModel.collection = .finished
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
        viewModel.collection = .recent
        viewModel.sort = .segments
        viewModel.books = [
            book(id: "short", title: "Short", segmentCount: 3),
            book(id: "long", title: "Long", segmentCount: 40),
            book(id: "mid", title: "Mid", segmentCount: 12),
        ]

        XCTAssertEqual(viewModel.displayedBooks.map(\.id), ["long", "mid", "short"])
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

    func testFromPersistedRestoresUnreadAndReading() {
        XCTAssertEqual(LibraryCollection.fromPersisted("unread"), .unread)
        XCTAssertEqual(LibraryCollection.fromPersisted("reading"), .reading)
        XCTAssertEqual(LibraryCollection.fromPersisted("all"), .recent)
        XCTAssertEqual(LibraryCollection.fromPersisted("文学"), .category("文学"))
    }
}
