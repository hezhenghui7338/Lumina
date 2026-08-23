import XCTest
@testable import Lumina

final class SummarizeActivityChipTests: XCTestCase {
    func testStatusLabel_omitsQueuedWhenZero() {
        XCTAssertEqual(
            SummarizeActivityChip.statusLabel(running: 2, queued: 0),
            "2 进行中"
        )
    }

    func testStatusLabel_includesQueuedWhenPositive() {
        XCTAssertEqual(
            SummarizeActivityChip.statusLabel(running: 1, queued: 3),
            "1 进行中 · 3 排队"
        )
    }

    func testShouldShow_onlyWhenActive() {
        XCTAssertFalse(SummarizeActivityChip.shouldShow(activeCount: 0))
        XCTAssertTrue(SummarizeActivityChip.shouldShow(activeCount: 1))
    }
}
