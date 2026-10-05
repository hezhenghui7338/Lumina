import XCTest
@testable import Lumina

final class FullscreenFeedGateTests: XCTestCase {
    private func segs(_ idxs: [Int]) -> [SegmentRow] {
        idxs.map {
            SegmentRow(
                id: "s\($0)", idx: $0, label: nil, chapter: nil, summary_status: "ready",
                summary_json: nil, raw_text: nil, translation: nil, anchor_label: nil,
                summary_provider: nil, summary_model: nil, summary_tier: nil, char_count: nil,
                retry_count: nil, summary_duration_s: nil, summary_llm_attempts: nil
            )
        }
    }

    func testRadiusIsPositive() {
        XCTAssertGreaterThan(FullscreenFeedGate.radius, 0)
        XCTAssertGreaterThan(FullscreenFeedGate.settleNanoseconds, 0)
    }

    func testEventEngagesGateOnWillOnly() {
        XCTAssertTrue(FullscreenFeedGate.Event.willEnter.engagesGate)
        XCTAssertTrue(FullscreenFeedGate.Event.willExit.engagesGate)
        XCTAssertFalse(FullscreenFeedGate.Event.didEnter.engagesGate)
        XCTAssertFalse(FullscreenFeedGate.Event.didExit.engagesGate)
    }

    func testSliceAroundPin() {
        let rows = segs(Array(0..<100))
        let sliced = FullscreenFeedGate.slice(segments: rows, pinIndex: 50, radius: 2)
        XCTAssertEqual(sliced.map(\.idx), [48, 49, 50, 51, 52])
    }

    func testSliceClampsAtEnds() {
        let rows = segs(Array(0..<10))
        XCTAssertEqual(
            FullscreenFeedGate.slice(segments: rows, pinIndex: 0, radius: 3).map(\.idx),
            [0, 1, 2, 3]
        )
        XCTAssertEqual(
            FullscreenFeedGate.slice(segments: rows, pinIndex: 9, radius: 3).map(\.idx),
            [6, 7, 8, 9]
        )
    }

    func testSliceEmptyAndMissingPin() {
        XCTAssertTrue(FullscreenFeedGate.slice(segments: [], pinIndex: 3).isEmpty)
        let rows = segs([0, 2, 4, 6])
        let sliced = FullscreenFeedGate.slice(segments: rows, pinIndex: 3, radius: 1)
        XCTAssertEqual(sliced.map(\.idx), [0, 2, 4])
    }

    func testSliceNilPinUsesFirst() {
        let rows = segs([5, 6, 7, 8])
        let sliced = FullscreenFeedGate.slice(segments: rows, pinIndex: nil, radius: 1)
        XCTAssertEqual(sliced.map(\.idx), [5, 6])
    }

    func testReaderFeedKeepsFullForEachAndGatedSlice() throws {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let reader = try String(
            contentsOf: macosRoot.appendingPathComponent("Lumina/Features/Reader/ReaderView.swift"),
            encoding: .utf8
        )
        XCTAssertTrue(
            reader.contains("ForEach(viewModel.segments, id: \\.idx)"),
            "steady-state must keep full ForEach (d383158)"
        )
        XCTAssertTrue(reader.contains("fullscreenFeedGated"))
        XCTAssertTrue(reader.contains("FullscreenFeedGate.slice"))
        XCTAssertTrue(reader.contains("luminaFullscreenTransition"))
        XCTAssertTrue(
            reader.contains("shouldSuppressFeedChurn"),
            "gated transition must suppress viewport/prefetch churn"
        )
    }

    func testLayoutPerfForwardsFullscreenToReader() throws {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let perf = try String(
            contentsOf: macosRoot.appendingPathComponent(
                "Lumina/Features/Shared/LuminaLayoutPerf.swift"
            ),
            encoding: .utf8
        )
        XCTAssertTrue(perf.contains("luminaFullscreenTransition"))
        XCTAssertTrue(perf.contains("userInfo: [\"kind\": kind]"))
    }
}
