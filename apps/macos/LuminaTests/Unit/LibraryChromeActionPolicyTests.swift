import XCTest
@testable import Lumina

final class LibraryChromeActionPolicyTests: XCTestCase {
    func testAllReadingAndBrowseLayouts_haveUniqueToolbarActions() {
        let layouts: [(hasBook: Bool, pinned: Bool)] = [
            (false, false),
            (false, true),
            (true, false),
            (true, true),
        ]
        for layout in layouts {
            let surfaces = LibraryChromeActionPolicy.windowToolbarSurfaces(
                hasSelectedBook: layout.hasBook,
                recentsPinned: layout.pinned
            )
            XCTAssertTrue(
                LibraryChromeActionPolicy.duplicateActions(among: surfaces).isEmpty,
                "layout book=\(layout.hasBook) pinned=\(layout.pinned)"
            )
        }
    }

    func testReadingWithRecentsPinned_hasNoDuplicateToolbarActions() {
        let duplicates = LibraryChromeActionPolicy.duplicateActions(
            among: [.reader, .recentsSidebar]
        )
        XCTAssertTrue(duplicates.isEmpty)
    }

    func testRecentsSidebar_contributesNoWindowToolbarActions() {
        XCTAssertTrue(
            LibraryChromeActionPolicy.toolbarActions(on: .recentsSidebar).isEmpty
        )
    }

    func testReaderOwnsSingleImportAndBookshelfActions() {
        let reader = LibraryChromeActionPolicy.toolbarActions(on: .reader)
        let recents = LibraryChromeActionPolicy.toolbarActions(on: .recentsSidebar)
        XCTAssertTrue(reader.contains(.importBook))
        XCTAssertTrue(reader.contains(.bookshelf))
        XCTAssertFalse(recents.contains(.importBook))
        XCTAssertFalse(recents.contains(.bookshelf))
        XCTAssertEqual(reader.intersection(recents), [])
    }

    func testLibraryContextMenu_alwaysOffersResegment() {
        let ready = BookSummary(
            id: "b1", title: "Ready", status: "reading", segment_count: 4
        )
        XCTAssertEqual(
            LibraryBookContextMenuPolicy.actions(for: ready),
            [.favorite, .reclassify, .resegment, .exportMarkdown, .delete]
        )
        XCTAssertTrue(LibraryBookContextMenuPolicy.isEnabled(.resegment, for: ready))

        let summarizing = BookSummary(
            id: "b2",
            title: "Summarizing",
            status: "reading",
            segment_count: 4,
            summary_ready_count: 1,
            summary_total_count: 4,
            summarize_state: "running"
        )
        XCTAssertTrue(
            LibraryBookContextMenuPolicy.actions(for: summarizing).contains(.resegment)
        )
        XCTAssertTrue(LibraryBookContextMenuPolicy.isEnabled(.resegment, for: summarizing))

        let processing = BookSummary(
            id: "b3", title: "Busy", status: "processing", segment_count: 4
        )
        XCTAssertTrue(
            LibraryBookContextMenuPolicy.actions(for: processing).contains(.resegment)
        )
        XCTAssertFalse(LibraryBookContextMenuPolicy.isEnabled(.resegment, for: processing))
    }
}
