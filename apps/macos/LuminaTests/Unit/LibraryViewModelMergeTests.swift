import XCTest
@testable import Lumina

@MainActor
final class LibraryViewModelMergeTests: XCTestCase {
    private func book(
        id: String,
        title: String = "Book",
        status: String = "reading",
        summaryReady: Int? = nil,
        summaryTotal: Int? = nil,
        summarizeState: String? = nil,
        lastOpenedAt: String? = nil
    ) -> BookSummary {
        BookSummary(
            id: id,
            title: title,
            status: status,
            segment_count: 10,
            last_opened_at: lastOpenedAt,
            summary_ready_count: summaryReady,
            summary_total_count: summaryTotal,
            summarize_state: summarizeState
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

    func testDisplayedBooks_prioritizesSummarizeActivityWhenRecentAndAll() {
        let viewModel = LibraryViewModel()
        viewModel.sort = .recent
        viewModel.summarizeStateFilter = .all
        viewModel.books = [
            book(id: "idle", summarizeState: "idle"),
            book(id: "running", summarizeState: "running"),
            book(id: "recent", lastOpenedAt: "2024-05-01T00:00:00Z"),
            book(id: "queued", summarizeState: "queued"),
        ]

        XCTAssertEqual(viewModel.displayedBooks.map(\.id), ["running", "queued", "idle", "recent"])
    }

    func testDisplayedBooks_doesNotReorderForTitleSort() {
        let viewModel = LibraryViewModel()
        viewModel.sort = .title
        viewModel.summarizeStateFilter = .all
        viewModel.books = [
            book(id: "idle", summarizeState: "idle"),
            book(id: "running", summarizeState: "running"),
            book(id: "queued", summarizeState: "queued"),
        ]

        XCTAssertEqual(viewModel.displayedBooks.map(\.id), ["idle", "running", "queued"])
    }
}
