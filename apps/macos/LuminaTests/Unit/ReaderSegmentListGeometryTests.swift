import CoreGraphics
import XCTest
@testable import Lumina

final class ReaderSegmentListGeometryTests: XCTestCase {
    private let segmentsWidth: CGFloat = 240

    func testIsPointerInSegmentList_headerPinButtonArea() {
        XCTAssertTrue(
            ReaderSegmentListGeometry.isPointerInSegmentList(
                CGPoint(x: 100, y: 15),
                segmentsWidth: segmentsWidth
            )
        )
    }

    func testIsPointerInSegmentList_bodyArea() {
        XCTAssertTrue(
            ReaderSegmentListGeometry.isPointerInSegmentList(
                CGPoint(x: 100, y: 200),
                segmentsWidth: segmentsWidth
            )
        )
    }

    func testIsPointerInSegmentList_outsideReadingArea() {
        XCTAssertFalse(
            ReaderSegmentListGeometry.isPointerInSegmentList(
                CGPoint(x: 300, y: 200),
                segmentsWidth: segmentsWidth
            )
        )
    }

    func testIsPointerInSegmentList_leftEdgeTopStillCountsAsInList() {
        XCTAssertTrue(
            ReaderSegmentListGeometry.isPointerInSegmentList(
                CGPoint(x: 5, y: 15),
                segmentsWidth: segmentsWidth
            )
        )
    }
}

final class ReaderSegmentPanelHeightTests: XCTestCase {
    func testClampBelowMinimum() {
        XCTAssertEqual(ReaderSegmentPanelHeight.clamp(80), 160)
    }

    func testClampAboveMaximum() {
        XCTAssertEqual(ReaderSegmentPanelHeight.clamp(800), 420)
    }

    func testClampWithinRange() {
        XCTAssertEqual(ReaderSegmentPanelHeight.clamp(300), 300)
    }

    func testBoxedViewportHeightUsesLockedWhenHigherThanCappedMeasured() {
        XCTAssertEqual(
            ReaderSegmentPanelHeight.boxedViewportHeight(measured: 300, locked: 360),
            360
        )
    }

    func testBoxedViewportHeightUsesCappedMeasuredWhenLockedIsStaleLow() {
        XCTAssertEqual(
            ReaderSegmentPanelHeight.boxedViewportHeight(measured: 300, locked: 160),
            300
        )
    }

    func testBoxedViewportHeightWithoutLock() {
        XCTAssertEqual(
            ReaderSegmentPanelHeight.boxedViewportHeight(measured: 800, locked: nil),
            420
        )
    }
}
