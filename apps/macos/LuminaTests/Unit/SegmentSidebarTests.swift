import XCTest
@testable import Lumina

final class SegmentSidebarTests: XCTestCase {
    func testSlice_centerIncludesBuffer() {
        let all = Array(0..<100)
        let window = SegmentRenderWindow.slice(all, centerIndex: 50, buffer: 20)
        XCTAssertEqual(window.startIndex, 30)
        XCTAssertEqual(window.items.count, 41)
        XCTAssertEqual(window.aboveCount, 30)
        XCTAssertEqual(window.belowCount, 29)
        XCTAssertEqual(window.totalCount, 100)
        XCTAssertEqual(window.aboveCount + window.items.count + window.belowCount, 100)
    }

    func testSlice_clampsAtStartAndEnd() {
        let all = Array(0..<10)
        let start = SegmentRenderWindow.slice(all, centerIndex: 0, buffer: 20)
        XCTAssertEqual(start.startIndex, 0)
        XCTAssertEqual(start.items.count, 10)
        XCTAssertEqual(start.aboveCount, 0)
        XCTAssertEqual(start.belowCount, 0)

        let end = SegmentRenderWindow.slice(all, centerIndex: 9, buffer: 20)
        XCTAssertEqual(end.startIndex, 0)
        XCTAssertEqual(end.items.count, 10)
    }

    func testSlice_emptyInput() {
        let window = SegmentRenderWindow.slice([Int](), centerIndex: 0, buffer: 20)
        XCTAssertTrue(window.isEmpty)
        XCTAssertEqual(window.items.count, 0)
    }

    func testCenterIndex_forSegmentIdx() {
        let segments = [
            SegmentRow(id: "a", idx: 0, label: nil, chapter: nil, summary_status: "ready", summary_json: nil, raw_text: nil, translation: nil, anchor_label: nil, summary_provider: nil, summary_model: nil, char_count: nil, retry_count: nil, summary_duration_s: nil, summary_llm_attempts: nil),
            SegmentRow(id: "b", idx: 5, label: nil, chapter: nil, summary_status: "pending", summary_json: nil, raw_text: nil, translation: nil, anchor_label: nil, summary_provider: nil, summary_model: nil, char_count: nil, retry_count: nil, summary_duration_s: nil, summary_llm_attempts: nil),
        ]
        XCTAssertEqual(SegmentRenderWindow.centerIndex(forSegmentIdx: 5, in: segments), 1)
        XCTAssertEqual(SegmentRenderWindow.centerIndex(forSegmentIdx: 99, in: segments), 0)
    }

    func testSegmentIndexDelta() {
        let segments = (0..<50).map { i in
            SegmentRow(
                id: "s\(i)", idx: i, label: nil, chapter: nil, summary_status: "ready",
                summary_json: nil, raw_text: nil, translation: nil, anchor_label: nil,
                summary_provider: nil, summary_model: nil, char_count: nil, retry_count: nil,
                summary_duration_s: nil, summary_llm_attempts: nil
            )
        }
        XCTAssertEqual(SegmentRenderWindow.segmentIndexDelta(from: 0, to: 10, in: segments), 10)
        XCTAssertEqual(SegmentRenderWindow.segmentIndexDelta(from: nil, to: 10, in: segments), Int.max)
    }

    func testSidebarSegmentItem_usesLabelFirst() {
        let segment = SegmentRow(
            id: "s1", idx: 0, label: "引子", chapter: "第一章", summary_status: "ready",
            summary_json: nil, raw_text: nil, translation: nil, anchor_label: nil,
            summary_provider: nil, summary_model: nil, char_count: nil, retry_count: nil,
            summary_duration_s: nil, summary_llm_attempts: nil
        )
        let item = SidebarSegmentItem.make(from: segment, bulletPreview: "preview", runningMetrics: nil)
        XCTAssertEqual(item.outlineLabel, "引子")
        XCTAssertNil(item.bulletPreview)
        XCTAssertEqual(item.chapterTitle, "第一章")
    }

    func testSidebarSegmentItem_pendingUsesStaticCopy() {
        let segment = SegmentRow(
            id: "s1", idx: 0, label: nil, chapter: nil, summary_status: "pending",
            summary_json: nil, raw_text: nil, translation: nil, anchor_label: nil,
            summary_provider: nil, summary_model: nil, char_count: nil, retry_count: nil,
            summary_duration_s: nil, summary_llm_attempts: nil
        )
        let item = SidebarSegmentItem.make(from: segment, bulletPreview: nil, runningMetrics: nil)
        XCTAssertEqual(item.outlineLabel, "等待摘要…")
    }
}

@MainActor
final class ReaderViewModelSidebarTests: XCTestCase {
    func testArrayIndex_forSegmentIdx() {
        let vm = ReaderViewModel()
        vm.segments = Self.sampleSegments(count: 10)
        vm.rebuildSidebarItems()

        XCTAssertEqual(vm.arrayIndex(forSegmentIdx: 0), 0)
        XCTAssertEqual(vm.arrayIndex(forSegmentIdx: 9), 9)
        XCTAssertNil(vm.arrayIndex(forSegmentIdx: 99))
    }

    func testPatchSidebarItems_updatesOnlyTarget() {
        let vm = ReaderViewModel()
        vm.segments = Self.sampleSegments(count: 5)
        vm.rebuildSidebarItems()

        let before0 = vm.sidebarItems[0]
        let before2 = vm.sidebarItems[2]
        let before1 = vm.sidebarItems[1]

        vm.segments[1].label = "更新标签"
        vm.patchSidebarItems(atSegmentIndices: [1])

        XCTAssertEqual(vm.sidebarItems[0], before0)
        XCTAssertEqual(vm.sidebarItems[2], before2)
        XCTAssertNotEqual(vm.sidebarItems[1], before1)
        XCTAssertEqual(vm.sidebarItems[1].outlineLabel, "更新标签")
    }

    private static func sampleSegments(count: Int) -> [SegmentRow] {
        (0..<count).map { i in
            SegmentRow(
                id: "s\(i)", idx: i, label: nil, chapter: "章 \(i + 1)", summary_status: "ready",
                summary_json: nil, raw_text: nil, translation: nil, anchor_label: nil,
                summary_provider: nil, summary_model: nil, char_count: nil, retry_count: nil,
                summary_duration_s: nil, summary_llm_attempts: nil
            )
        }
    }
}
