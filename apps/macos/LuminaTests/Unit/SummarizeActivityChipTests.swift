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
                segmentListVisible: false
            )
        )
    }

    func testReaderContentBanner_hidesWhenSegmentListOpen() {
        XCTAssertFalse(
            ReaderSummaryProgressPolicy.shouldShowContentBanner(
                readyCount: 2,
                totalCount: 10,
                segmentListVisible: true
            )
        )
    }

    func testReaderContentBanner_hidesOnCompleteBook() {
        XCTAssertFalse(
            ReaderSummaryProgressPolicy.shouldShowContentBanner(
                readyCount: 10,
                totalCount: 10,
                segmentListVisible: false
            )
        )
        XCTAssertTrue(
            ReaderSummaryProgressPolicy.shouldShowContentBanner(
                readyCount: 9,
                totalCount: 10,
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
        XCTAssertTrue(
            source.contains("onStatusTap: openLibrarySummarizingCollection"),
            "tapping the 进行中/排队 chip must leave the reader for the bookshelf 摘要中 collection"
        )
        guard let start = source.range(of: "private func openLibrarySummarizingCollection"),
              let end = source.range(of: "private func stopAllSummarize")
        else {
            return XCTFail("could not isolate openLibrarySummarizingCollection in ReaderView.swift")
        }
        let jump = String(source[start.lowerBound..<end.lowerBound])
        XCTAssertTrue(
            jump.contains("SummarizeActivityNavigationPolicy.destinationCollection"),
            "the chip must select the 摘要中 sidebar collection"
        )
        XCTAssertTrue(
            jump.contains("onReturnToBookshelf()"),
            "the chip must leave the reader for the bookshelf"
        )
        XCTAssertTrue(
            jump.contains("flushProgressSave()"),
            "leaving via the chip must save reading progress like the back button"
        )
    }

    @MainActor
    func testStatusTap_opensSummarizingCollectionWithoutClearingOtherFacets() {
        XCTAssertEqual(
            SummarizeActivityNavigationPolicy.destinationCollection,
            .summarizing
        )
        XCTAssertEqual(
            SummarizeActivityNavigationPolicy.destinationCollection.label,
            "摘要中"
        )

        let viewModel = LibraryViewModel()
        viewModel.selectFacet(.unread)
        viewModel.selectFacet(SummarizeActivityNavigationPolicy.destinationCollection)
        XCTAssertEqual(viewModel.query.summary, .summarizing)
        XCTAssertEqual(viewModel.query.reading, .unread)
        XCTAssertTrue(viewModel.query.isSelected(.summarizing))
    }

    func testChipSource_statusTapIsSeparateFromStop() throws {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let source = try String(
            contentsOf: macosRoot.appendingPathComponent(
                "Lumina/Features/Library/SummarizeActivityChip.swift"
            ),
            encoding: .utf8
        )
        XCTAssertTrue(source.contains("var onStatusTap: (() -> Void)? = nil"))
        XCTAssertTrue(source.contains("Button(action: onStop)"))
        XCTAssertTrue(source.contains("Button(action: onStatusTap)"))
        XCTAssertTrue(source.contains("停止全部摘要"))
        XCTAssertTrue(source.contains("SummarizeActivityNavigationPolicy.statusTapHelp"))

        let bookshelf = try String(
            contentsOf: macosRoot.appendingPathComponent(
                "Lumina/Features/Library/BookshelfView.swift"
            ),
            encoding: .utf8
        )
        XCTAssertTrue(
            bookshelf.contains("onStatusTap:"),
            "bookshelf chip text must also jump to 摘要中; only x stops"
        )
        XCTAssertTrue(
            bookshelf.contains("SummarizeActivityNavigationPolicy.destinationCollection")
        )
    }

    /// Segment list used to duplicate 摘要 n/m + the activity chip already on the chrome bar.
    func testSegmentList_doesNotHostOverallSummaryProgress() throws {
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
        guard let start = source.range(of: "private var segmentCoverPanel"),
              let end = source.range(of: "private var sidebarHeaderButtons")
        else {
            return XCTFail("could not isolate segmentCoverPanel in ReaderView.swift")
        }
        let panel = String(source[start.lowerBound..<end.lowerBound])
        XCTAssertFalse(
            panel.contains("SummaryProgressBanner"),
            "segment list must not show book-level 摘要 n/m; the chrome bar already has it"
        )
        XCTAssertFalse(
            panel.contains("readerSummarizeActivityChip"),
            "segment list must not repeat the 进行中/排队 chip from the chrome bar"
        )
        XCTAssertFalse(source.contains("hideWhenComplete"))
    }

    func testSummaryProgressBannerReservedHeight_isConstant() {
        let height = SummaryProgressBannerMetrics.reservedHeight
        XCTAssertEqual(height, 82)
        XCTAssertEqual(
            SummaryProgressBannerMetrics.verticalPadding * 2
                + SummaryProgressBannerMetrics.titleLineHeight
                + SummaryProgressBannerMetrics.rowSpacing
                + SummaryProgressBannerMetrics.barHeight
                + SummaryProgressBannerMetrics.rowSpacing
                + SummaryProgressBannerMetrics.captionLineHeight
                + SummaryProgressBannerMetrics.rowSpacing
                + SummaryProgressBannerMetrics.activeLineHeight,
            height
        )
    }

    func testSummaryProgressBanner_alwaysReservesCaptionRows() throws {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let source = try String(
            contentsOf: macosRoot.appendingPathComponent(
                "Lumina/Features/Reader/SummaryProgressBanner.swift"
            ),
            encoding: .utf8
        )
        XCTAssertTrue(source.contains("frame(height: SummaryProgressBannerMetrics.reservedHeight"))
        XCTAssertFalse(
            source.contains("if let activityLabel"),
            "omitting the activity row when a caption is missing changes inset height"
        )
        XCTAssertFalse(
            source.contains("if totalCount > 0, readyCount < totalCount"),
            "hiding the whole banner body when the book completes while overview is active collapses the inset"
        )
        XCTAssertTrue(source.contains("captionRow("))
        XCTAssertTrue(source.contains(".lineLimit(1)"))
    }

    func testReaderFeedBannerInset_usesReservedHeight() throws {
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
        guard let start = source.range(of: ".scrollPosition(id: $topSegmentIdx, anchor: .top)"),
              let end = source.range(of: "ReaderChromeBarMetrics.height")
        else {
            return XCTFail("could not isolate the summary-progress inset in ReaderView.swift")
        }
        let inset = String(source[start.lowerBound..<end.lowerBound])
        XCTAssertTrue(
            inset.contains("SummaryProgressBannerMetrics.reservedHeight"),
            "the feed inset must keep a constant height while summarizing"
        )
        XCTAssertFalse(
            inset.contains("padding(.vertical"),
            "extra vertical padding on top of reservedHeight would make caption rows shift the feed"
        )
        XCTAssertTrue(
            inset.contains("transaction { $0.animation = nil }")
                || inset.contains(".animation(nil, value: shouldShowContentSummaryProgress)"),
            "showing or hiding the banner must not animate the feed sliding"
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
