import XCTest
@testable import Lumina

final class LibrarySidebarVisibilityPolicyTests: XCTestCase {
    func testShowsLibrarySidebar_noBookAlwaysShown() {
        XCTAssertTrue(
            LibrarySidebarVisibilityPolicy.showsLibrarySidebar(hasSelectedBook: false, pinned: false)
        )
        XCTAssertTrue(
            LibrarySidebarVisibilityPolicy.showsLibrarySidebar(hasSelectedBook: false, pinned: true)
        )
    }

    func testShowsLibrarySidebar_readingUnpinnedHidden() {
        XCTAssertFalse(
            LibrarySidebarVisibilityPolicy.showsLibrarySidebar(hasSelectedBook: true, pinned: false)
        )
    }

    func testShowsLibrarySidebar_readingPinnedShown() {
        XCTAssertTrue(
            LibrarySidebarVisibilityPolicy.showsLibrarySidebar(hasSelectedBook: true, pinned: true)
        )
    }
}
