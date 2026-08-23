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
}
