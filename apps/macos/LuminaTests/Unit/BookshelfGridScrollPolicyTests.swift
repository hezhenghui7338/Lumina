import XCTest
@testable import Lumina

final class BookshelfGridScrollPolicyTests: XCTestCase {
    /// Layout width permanently reserves the scroller gutter so cover aspect
    /// height cannot oscillate when a legacy scroller appears.
    func testLayoutWidth_alwaysReservesScrollerGutter() {
        let outer: CGFloat = 850
        let layout = BookshelfGridScrollPolicy.layoutWidth(forContainerWidth: outer)
        XCTAssertEqual(
            layout,
            outer
                - BookshelfGridScrollPolicy.contentPadding * 2
                - BookshelfGridScrollPolicy.scrollerGutter
        )
        // Content + horizontal padding equals outer − gutter (empty trailing strip).
        XCTAssertEqual(
            layout + BookshelfGridScrollPolicy.contentPadding * 2,
            outer - BookshelfGridScrollPolicy.scrollerGutter
        )
    }

    /// At common detail widths, measuring columns from scroller-inset content
    /// width (without reserving gutter) flips the count.
    func testColumnCount_scrollerGutterWouldFlipAtCommonWidths() {
        let outer: CGFloat = 850
        let withoutReserve = outer - BookshelfGridScrollPolicy.contentPadding * 2
        let withReserve = BookshelfGridScrollPolicy.layoutWidth(forContainerWidth: outer)
        XCTAssertEqual(
            BookshelfGridScrollPolicy.columnCount(forLayoutWidth: withoutReserve),
            5
        )
        XCTAssertEqual(
            BookshelfGridScrollPolicy.columnCount(forLayoutWidth: withReserve),
            4,
            "permanent gutter reservation must use the narrower column count"
        )
    }

    func testColumnCount_stableForPinnedLayoutWidth() {
        let width: CGFloat = 850
        let layout = BookshelfGridScrollPolicy.layoutWidth(forContainerWidth: width)
        XCTAssertEqual(
            BookshelfGridScrollPolicy.columnCount(forLayoutWidth: layout),
            BookshelfGridScrollPolicy.columnCount(forContainerWidth: width)
        )
        XCTAssertEqual(
            BookshelfGridScrollPolicy.gridItems(forLayoutWidth: layout).count,
            BookshelfGridScrollPolicy.columnCount(forLayoutWidth: layout)
        )
    }

    func testRows_padsIncompleteLastRowInput() {
        let books = ["a", "b", "c", "d", "e"]
        let rows = BookshelfGridScrollPolicy.rows(books: books, columnCount: 3)
        XCTAssertEqual(rows.count, 2)
        XCTAssertEqual(rows[0], ["a", "b", "c"])
        XCTAssertEqual(rows[1], ["d", "e"])
    }

    func testBookshelfView_pinsLayoutWidthAndAvoidsLazyAdaptiveGrid() throws {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let source = try String(
            contentsOf: macosRoot.appendingPathComponent(
                "Lumina/Features/Library/BookshelfView.swift"
            ),
            encoding: .utf8
        )
        guard let start = source.range(of: "private var bookGrid: some View"),
              let end = source.range(of: "private var bookList:")
        else {
            return XCTFail("could not isolate bookGrid in BookshelfView.swift")
        }
        let grid = String(source[start.lowerBound..<end.lowerBound])
        XCTAssertTrue(grid.contains("GeometryReader"))
        XCTAssertTrue(
            grid.contains("BookshelfGridScrollPolicy.layoutWidth"),
            "grid must pin width that already reserves the scroller gutter"
        )
        XCTAssertTrue(
            grid.contains("frame(width: layoutWidth"),
            "grid frame must be the pinned layout width, not ScrollView content width"
        )
        XCTAssertFalse(
            grid.contains("LazyVGrid"),
            "LazyVGrid content-size feedback amplifies scroller jitter on macOS"
        )
        XCTAssertFalse(grid.contains(".adaptive("))
    }

    func testBookCard_reservesStatusAndMeterSlots() throws {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let source = try String(
            contentsOf: macosRoot.appendingPathComponent(
                "Lumina/Features/Library/BookCard.swift"
            ),
            encoding: .utf8
        )
        XCTAssertTrue(
            source.contains("BookshelfGridCardMetrics.statusReservedHeight"),
            "status wrap must not change card height during summarize progress"
        )
        XCTAssertTrue(
            source.contains("BookshelfGridCardMetrics.meterReservedHeight"),
            "progress meter must sit in a fixed-height slot"
        )
        XCTAssertEqual(BookshelfGridCardMetrics.statusReservedHeight, 32)
        XCTAssertEqual(BookshelfGridCardMetrics.meterReservedHeight, 8)
    }
}
