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
            SegmentRow(id: "a", idx: 0, label: nil, chapter: nil, summary_status: "ready", summary_json: nil, raw_text: nil, translation: nil, anchor_label: nil, summary_provider: nil, summary_model: nil, summary_tier: nil, char_count: nil, retry_count: nil, summary_duration_s: nil, summary_llm_attempts: nil),
            SegmentRow(id: "b", idx: 5, label: nil, chapter: nil, summary_status: "pending", summary_json: nil, raw_text: nil, translation: nil, anchor_label: nil, summary_provider: nil, summary_model: nil, summary_tier: nil, char_count: nil, retry_count: nil, summary_duration_s: nil, summary_llm_attempts: nil),
        ]
        XCTAssertEqual(SegmentRenderWindow.centerIndex(forSegmentIdx: 5, in: segments), 1)
        XCTAssertEqual(SegmentRenderWindow.centerIndex(forSegmentIdx: 99, in: segments), 0)
    }

    func testSegmentIndexDelta() {
        let segments = (0..<50).map { i in
            SegmentRow(
                id: "s\(i)", idx: i, label: nil, chapter: nil, summary_status: "ready",
                summary_json: nil, raw_text: nil, translation: nil, anchor_label: nil,
                summary_provider: nil, summary_model: nil, summary_tier: nil, char_count: nil, retry_count: nil,
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
            summary_provider: nil, summary_model: nil, summary_tier: nil, char_count: nil, retry_count: nil,
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
            summary_provider: nil, summary_model: nil, summary_tier: nil, char_count: nil, retry_count: nil,
            summary_duration_s: nil, summary_llm_attempts: nil
        )
        let item = SidebarSegmentItem.make(from: segment, bulletPreview: nil, runningMetrics: nil)
        XCTAssertEqual(item.outlineLabel, "等待摘要…")
    }

    func testSidebarSegmentItem_runningUsesGeneratingCopy() {
        let segment = SegmentRow(
            id: "s1", idx: 0, label: nil, chapter: nil, summary_status: "running",
            summary_json: nil, raw_text: nil, translation: nil, anchor_label: nil,
            summary_provider: nil, summary_model: nil, summary_tier: nil, char_count: nil, retry_count: nil,
            summary_duration_s: nil, summary_llm_attempts: nil
        )
        let item = SidebarSegmentItem.make(from: segment, bulletPreview: nil, runningMetrics: nil)
        XCTAssertEqual(item.outlineLabel, "摘要生成中…")
    }
}

@MainActor
final class ReaderViewModelSidebarTests: XCTestCase {
    func testNormalizedResegmentTarget_usesCurrentTargetAndClampsRange() {
        XCTAssertEqual(
            ReaderViewModel.normalizedResegmentTarget(
                currentTarget: 3_449,
                totalChars: nil,
                segmentCount: 0
            ),
            3_400
        )
        XCTAssertEqual(
            ReaderViewModel.normalizedResegmentTarget(
                currentTarget: 900,
                totalChars: nil,
                segmentCount: 0
            ),
            900
        )
        XCTAssertEqual(
            ReaderViewModel.normalizedResegmentTarget(
                currentTarget: 50,
                totalChars: nil,
                segmentCount: 0
            ),
            ReaderViewModel.resegmentMinTargetChars
        )
        XCTAssertEqual(
            ReaderViewModel.normalizedResegmentTarget(
                currentTarget: 200,
                totalChars: nil,
                segmentCount: 0
            ),
            200
        )
        XCTAssertEqual(
            ReaderViewModel.normalizedResegmentTarget(
                currentTarget: 9_000,
                totalChars: nil,
                segmentCount: 0
            ),
            8_000
        )
    }

    func testNormalizedResegmentTarget_fallsBackToAverageSegmentSize() {
        XCTAssertEqual(
            ReaderViewModel.normalizedResegmentTarget(
                currentTarget: nil,
                totalChars: 10_100,
                segmentCount: 3
            ),
            3_400
        )
    }

    func testResegmentEventsUpdateReaderState() {
        let vm = ReaderViewModel()
        let core = CoreClient(baseURL: URL(string: "http://127.0.0.1:8765")!)

        vm.handleEvent(
            ["type": "resegment_started", "chunk_target_chars": 2_500],
            core: core
        )
        XCTAssertTrue(vm.isResegmenting)
        XCTAssertFalse(vm.isResegmentCancelling)
        XCTAssertEqual(vm.chunkTargetChars, 2_500)
        XCTAssertEqual(vm.ingestProgress?.message, "正在重新分段…")

        vm.handleEvent(
            ["type": "resegment_failed", "status": "reading", "message": "测试失败"],
            core: core
        )
        XCTAssertFalse(vm.isResegmenting)
        XCTAssertEqual(vm.bookStatus, "reading")
        XCTAssertEqual(vm.loadError, "测试失败")
    }

    func testSegmentProgressMessage_pendingDoesNotClaimGenerating() {
        let vm = ReaderViewModel()
        vm.segments = [
            SegmentRow(
                id: "s1", idx: 0, label: nil, chapter: nil, summary_status: "pending",
                summary_json: nil, raw_text: nil, translation: nil, anchor_label: nil,
                summary_provider: nil, summary_model: nil, summary_tier: nil, char_count: nil, retry_count: nil,
                summary_duration_s: nil, summary_llm_attempts: nil
            )
        ]
        XCTAssertNil(vm.segmentProgressMessage(for: 0))
        XCTAssertNil(vm.activeSummarizeLabel())
    }

    func testSegmentProgressMessage_runningShowsGenerating() {
        let vm = ReaderViewModel()
        vm.segments = [
            SegmentRow(
                id: "s1", idx: 0, label: nil, chapter: nil, summary_status: "running",
                summary_json: nil, raw_text: nil, translation: nil, anchor_label: nil,
                summary_provider: nil, summary_model: nil, summary_tier: nil, char_count: nil, retry_count: nil,
                summary_duration_s: nil, summary_llm_attempts: nil
            )
        ]
        XCTAssertEqual(vm.segmentProgressMessage(for: 0), "摘要生成中…")
        XCTAssertEqual(vm.activeSummarizeLabel(), "段 1 · 摘要生成中…")
    }

    func testSettingsChunkTargetRange_allows200() {
        for kind in ModelProviderKind.allCases {
            XCTAssertEqual(kind.chunkTargetRange.lowerBound, 200)
            XCTAssertTrue(kind.chunkTargetRange.contains(200))
        }
    }

}
