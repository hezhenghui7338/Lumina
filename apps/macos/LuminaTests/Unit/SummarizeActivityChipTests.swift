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

    /// Book index rollup used to hog every worker, leaving a bare 「0 进行中 · n 排队」.
    func testStatusLabel_indexingStallNeverReadsAsZeroRunning() {
        let label = SummarizeActivityChip.statusLabel(
            running: 0,
            queued: 3,
            indexing: 1,
            stalledReason: "indexing"
        )
        XCTAssertEqual(label, "3 排队 · 1 建索引 · 正在建索引")
        XCTAssertFalse(label.contains("0 进行中"))
    }

    func testStatusLabel_chatPreemptExplainsIdleQueue() {
        let label = SummarizeActivityChip.statusLabel(
            running: 0,
            queued: 2,
            stalledReason: "chat_preempt"
        )
        XCTAssertEqual(label, "2 排队 · 深聊占用模型")
        XCTAssertFalse(label.contains("0 进行中"))
    }

    func testStatusLabel_runningKeepsIndexingVisible() {
        XCTAssertEqual(
            SummarizeActivityChip.statusLabel(running: 2, queued: 1, indexing: 1),
            "2 进行中 · 1 排队 · 1 建索引"
        )
    }

    func testStatusLabel_unknownStallReasonStillOmitsZeroRunning() {
        XCTAssertEqual(
            SummarizeActivityChip.statusLabel(running: 0, queued: 4, stalledReason: nil),
            "4 排队"
        )
    }

    func testOverviewActiveCount_countsIndexingOnlyWork() throws {
        let json = """
        {
          "counts": {
            "running": 0, "queued": 0, "paused": 0,
            "idle": 5, "summarized": 9, "indexing": 1
          },
          "indexing_queued": 2,
          "stalled_reason": null,
          "user_paused_all": false
        }
        """
        let overview = try JSONDecoder().decode(
            SummarizeOverview.self, from: Data(json.utf8)
        )
        XCTAssertEqual(overview.indexingCount, 1)
        XCTAssertEqual(overview.indexing_queued, 2)
        XCTAssertNil(overview.stalled_reason)
        XCTAssertTrue(SummarizeActivityChip.shouldShow(activeCount: overview.activeCount))
    }

    /// Older sidecars omit the new fields; decoding must not fail.
    func testOverview_decodesLegacyPayloadWithoutIndexingFields() throws {
        let json = """
        {
          "counts": {"running": 1, "queued": 2, "paused": 0, "idle": 0, "summarized": 3},
          "user_paused_all": false
        }
        """
        let overview = try JSONDecoder().decode(
            SummarizeOverview.self, from: Data(json.utf8)
        )
        XCTAssertEqual(overview.indexingCount, 0)
        XCTAssertEqual(overview.activeCount, 3)
        XCTAssertNil(overview.stalled_reason)
    }

    func testReaderContentBanner_showsWhenRecentsSidebarPinned() {
        XCTAssertTrue(
            ReaderSummaryProgressPolicy.shouldShowContentBanner(
                readyCount: 2,
                totalCount: 10,
                overviewActive: false,
                segmentListVisible: false
            )
        )
    }

    func testReaderContentBanner_hidesWhenSegmentListAlreadyShowsIt() {
        XCTAssertFalse(
            ReaderSummaryProgressPolicy.shouldShowContentBanner(
                readyCount: 2,
                totalCount: 10,
                overviewActive: true,
                segmentListVisible: true
            )
        )
    }

    func testReaderContentBanner_showsLibraryQueueOnCompleteBook() {
        XCTAssertTrue(
            ReaderSummaryProgressPolicy.shouldShowContentBanner(
                readyCount: 10,
                totalCount: 10,
                overviewActive: true,
                segmentListVisible: false
            )
        )
        XCTAssertFalse(
            ReaderSummaryProgressPolicy.shouldShowContentBanner(
                readyCount: 10,
                totalCount: 10,
                overviewActive: false,
                segmentListVisible: false
            )
        )
    }

    func testQueuedCount_onlyAfterSummarizeStarted() {
        let segments = [
            stubSegment(idx: 0, status: "ready"),
            stubSegment(idx: 1, status: "running"),
            stubSegment(idx: 2, status: "pending"),
            stubSegment(idx: 3, status: "pending"),
        ]
        XCTAssertEqual(
            ReaderSummaryProgressPolicy.queuedCount(in: segments, summarizeState: "idle"),
            0
        )
        XCTAssertEqual(
            ReaderSummaryProgressPolicy.queuedCount(in: segments, summarizeState: "running"),
            2
        )
        XCTAssertEqual(ReaderSummaryProgressPolicy.runningCount(in: segments), 1)
        XCTAssertEqual(
            ReaderSummaryProgressPolicy.activityLabel(running: 1, queued: 2),
            "1 进行中 · 2 排队"
        )
    }

    func testReaderView_showsSummarizeActivityOnReadingSurface() throws {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let source = try String(
            contentsOf: macosRoot.appendingPathComponent(
                "Lumina/Features/Reader/ReaderView.swift"
            ),
            encoding: .utf8
        )
        XCTAssertTrue(
            source.contains("readerSummarizeActivityChip"),
            "reading surface must host the library-wide 进行中/排队 chip"
        )
        XCTAssertTrue(
            source.contains("if librarySummarizeOverviewActive"),
            "reader toolbar must show the activity chip when chrome is visible"
        )
        XCTAssertTrue(source.contains("activityLabel: viewModel.summarizeActivityLabel"))
        XCTAssertFalse(
            source.contains("&& !librarySidebarPinned"),
            "pinning recents must not hide reading-surface summarize progress"
        )
    }

    private func stubSegment(idx: Int, status: String) -> SegmentRow {
        SegmentRow(
            id: "s\(idx)", idx: idx, label: nil, chapter: nil, summary_status: status,
            summary_json: nil, raw_text: nil, translation: nil, anchor_label: nil,
            summary_provider: nil, summary_model: nil, summary_tier: nil, char_count: nil,
            retry_count: nil, summary_duration_s: nil, summary_llm_attempts: nil
        )
    }
}
