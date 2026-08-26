import XCTest
@testable import Lumina

final class LibrarySidebarVisibilityPolicyTests: XCTestCase {
    func testShowsLibrarySidebar_noBookAlwaysShown() {
        XCTAssertTrue(
            LibrarySidebarVisibilityPolicy.showsLibrarySidebar(hasSelectedBook: false)
        )
    }

    func testShowsLibrarySidebar_readingNeverShowsAColumn() {
        XCTAssertFalse(
            LibrarySidebarVisibilityPolicy.showsLibrarySidebar(hasSelectedBook: true)
        )
    }

    func testSidebarUsesIndependentFacetsInsteadOfSingleSelection() throws {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let source = try String(
            contentsOf: macosRoot.appendingPathComponent(
                "Lumina/Features/Library/LibraryCollectionSidebar.swift"
            ),
            encoding: .utf8
        )
        XCTAssertFalse(
            source.contains("List(selection:"),
            "single List selection cannot keep 摘要/阅读/分类 independent"
        )
        XCTAssertTrue(source.contains("selectFacet"))
        XCTAssertTrue(source.contains("isSelected"))
    }
}
