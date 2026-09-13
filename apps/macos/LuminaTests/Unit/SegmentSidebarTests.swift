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

    func testReadingWindow_farJump100_staysBoundedAndContainsTarget() {
        let segments = (0..<250).map { i in
            SegmentRow(
                id: "s\(i)", idx: i, label: nil, chapter: nil, summary_status: "ready",
                summary_json: nil, raw_text: nil, translation: nil, anchor_label: nil,
                summary_provider: nil, summary_model: nil, summary_tier: nil, char_count: nil, retry_count: nil,
                summary_duration_s: nil, summary_llm_attempts: nil
            )
        }
        let from = 20
        let to = from + 100
        XCTAssertEqual(
            SegmentRenderWindow.segmentIndexDelta(from: from, to: to, in: segments),
            100
        )
        XCTAssertGreaterThan(
            SegmentRenderWindow.segmentIndexDelta(from: from, to: to, in: segments),
            SegmentRenderWindow.scrollAnimateThreshold
        )

        let window = SegmentRenderWindow.readingWindow(segments: segments, pinnedIdx: to)
        let maxItems = 2 * SegmentRenderWindow.readRenderBuffer + 1
        XCTAssertLessThanOrEqual(window.items.count, maxItems)
        XCTAssertTrue(window.items.contains(where: { $0.idx == to }))
        XCTAssertEqual(window.aboveCount + window.items.count + window.belowCount, segments.count)
        // Pin cost must not grow with jump distance: same bound as a nearby pin.
        let nearby = SegmentRenderWindow.readingWindow(segments: segments, pinnedIdx: from + 1)
        XCTAssertEqual(window.items.count, nearby.items.count)
    }

    func testOffscreenSpacerHeight_scalesWithCount() {
        XCTAssertEqual(SegmentRenderWindow.offscreenSpacerHeight(count: 0), 0)
        XCTAssertEqual(
            SegmentRenderWindow.offscreenSpacerHeight(count: 100),
            100 * SegmentRenderWindow.offscreenSegmentEstimate
        )
    }

    func testReadingWindow_hysteresis_keepsAnchorWithinThreshold() {
        let segments = (0..<100).map { i in
            SegmentRow(
                id: "s\(i)", idx: i, label: nil, chapter: nil, summary_status: "ready",
                summary_json: nil, raw_text: nil, translation: nil, anchor_label: nil,
                summary_provider: nil, summary_model: nil, summary_tier: nil, char_count: nil, retry_count: nil,
                summary_duration_s: nil, summary_llm_attempts: nil
            )
        }
        let initialAnchor = 30
        // Small movement within hysteresis threshold keeps the original anchor and slice bounds
        let smallScroll = initialAnchor + 3
        let stabilized = SegmentRenderWindow.stabilizedAnchor(
            currentPinnedIdx: smallScroll,
            existingAnchorIdx: initialAnchor,
            in: segments
        )
        XCTAssertEqual(stabilized, initialAnchor)

        let windowA = SegmentRenderWindow.readingWindow(
            segments: segments,
            pinnedIdx: initialAnchor,
            anchorIdx: initialAnchor
        )
        let windowB = SegmentRenderWindow.readingWindow(
            segments: segments,
            pinnedIdx: smallScroll,
            anchorIdx: initialAnchor
        )
        XCTAssertEqual(windowA.aboveCount, windowB.aboveCount)
        XCTAssertEqual(windowA.startIndex, windowB.startIndex)
        XCTAssertEqual(windowA.items.map(\.idx), windowB.items.map(\.idx))

        // Large scroll past threshold re-anchors to the current pin
        let largeScroll = initialAnchor + SegmentRenderWindow.hysteresisThreshold + 2
        let reanchored = SegmentRenderWindow.stabilizedAnchor(
            currentPinnedIdx: largeScroll,
            existingAnchorIdx: initialAnchor,
            in: segments
        )
        XCTAssertEqual(reanchored, largeScroll)
    }

    func testSidebarSegmentItem_prefersChapterTitleOverLabel() {
        let segment = SegmentRow(
            id: "s1", idx: 0, label: "引子", chapter: "第一章", summary_status: "ready",
            summary_json: nil, raw_text: nil, translation: nil, anchor_label: nil,
            summary_provider: nil, summary_model: nil, summary_tier: nil, char_count: nil, retry_count: nil,
            summary_duration_s: nil, summary_llm_attempts: nil,
            summary_preview: "主角生于贫苦农家，父亲早逝，母亲靠纺织维生。",
            bullet_labels: ["寒门出身", "赴考之志"]
        )
        let item = SidebarSegmentItem.make(from: segment)
        XCTAssertEqual(item.title, "第一章")
        XCTAssertEqual(item.headline, "段 1 · 第一章")
        XCTAssertEqual(item.summaryPreview, "主角生于贫苦农家，父亲早逝，母亲靠纺织维生。")
        XCTAssertEqual(item.bulletLabelsLine, "寒门出身 · 赴考之志")
        let fromList = SidebarSegmentItem.make(
            from: SegmentRow(
                id: "s1", idx: 0, label: "引子", chapter: "第一章", summary_status: "ready",
                summary_json: nil, raw_text: nil, translation: nil, anchor_label: nil,
                summary_provider: nil, summary_model: nil, summary_tier: nil, char_count: nil, retry_count: nil,
                summary_duration_s: nil, summary_llm_attempts: nil,
                summary_preview: "主角生于贫苦农家，父亲早逝，母亲靠纺织维生。"
            )
        )
        XCTAssertEqual(
            fromList.summaryPreview,
            "主角生于贫苦农家，父亲早逝，母亲靠纺织维生。"
        )
        XCTAssertNil(fromList.bulletLabelsLine)
    }

    func testSidebarSegmentItem_stripsSectionMarkFromChapterTitle() {
        let segment = SegmentRow(
            id: "s1", idx: 0, label: "引子", chapter: "§§第一章", summary_status: "ready",
            summary_json: nil, raw_text: nil, translation: nil, anchor_label: nil,
            summary_provider: nil, summary_model: nil, summary_tier: nil, char_count: nil, retry_count: nil,
            summary_duration_s: nil, summary_llm_attempts: nil
        )
        let item = SidebarSegmentItem.make(from: segment)
        XCTAssertEqual(item.title, "第一章")
        XCTAssertEqual(item.headline, "段 1 · 第一章")
        XCTAssertFalse(item.headline.contains("§"))
        XCTAssertEqual(SegmentOutlinePolicy.stripSectionMark("第一章§"), "第一章")
        XCTAssertEqual(
            SegmentCatalogHeadlineText.title(chapter: "卷一 §", label: "引子"),
            "卷一"
        )
    }

    func testSidebarSegmentItem_groupedOmitsChapterFromHeadline() {
        let segment = SegmentRow(
            id: "s1", idx: 0, label: "引子", chapter: "第一章", summary_status: "ready",
            summary_json: nil, raw_text: nil, translation: nil, anchor_label: nil,
            summary_provider: nil, summary_model: nil, summary_tier: nil, char_count: nil, retry_count: nil,
            summary_duration_s: nil, summary_llm_attempts: nil
        )
        let item = SidebarSegmentItem.make(from: segment, grouped: true)
        XCTAssertEqual(item.title, "引子")
        XCTAssertEqual(item.headline, "段 1 · 引子")
    }

    func testSidebarSegmentItem_usesLabelWhenNoChapter() {
        let segment = SegmentRow(
            id: "s1", idx: 0, label: "引子", chapter: nil, summary_status: "ready",
            summary_json: nil, raw_text: nil, translation: nil, anchor_label: nil,
            summary_provider: nil, summary_model: nil, summary_tier: nil, char_count: nil, retry_count: nil,
            summary_duration_s: nil, summary_llm_attempts: nil
        )
        let item = SidebarSegmentItem.make(from: segment)
        XCTAssertEqual(item.title, "引子")
        XCTAssertEqual(item.headline, "段 1 · 引子")
    }

    func testCatalogHeadlineText_ignoresBlankChapterAndLabel() {
        XCTAssertEqual(
            SegmentCatalogHeadlineText.title(chapter: "  第一章  ", label: "引子"),
            "第一章"
        )
        XCTAssertEqual(
            SegmentCatalogHeadlineText.title(chapter: "   ", label: " 引子 "),
            "引子"
        )
        XCTAssertNil(SegmentCatalogHeadlineText.title(chapter: nil, label: nil))
        XCTAssertEqual(SegmentCatalogHeadlineText.joined(idx: 0, title: nil), "段 1")
        XCTAssertEqual(SegmentCatalogHeadlineText.joined(idx: 4, title: "学而"), "段 5 · 学而")
    }

    func testCatalogPreview_usesSentenceNotInferredLabelPrefix() {
        let inferred = "邻里虽敬"
        let sentence = "邻里虽敬其向学，却无力资助书卷。"
        XCTAssertEqual(
            SegmentCatalogPreview.line(summaryPreview: sentence),
            sentence
        )
        XCTAssertNotEqual(
            SegmentCatalogPreview.line(summaryPreview: sentence),
            inferred
        )
        let json = """
        {"sentences":["\(sentence)"],"bullets":[{"label":"邻里","body":"乡邻敬其向学。"}],"label":"\(inferred)"}
        """
        XCTAssertEqual(SegmentCatalogPreview.fromSummaryJSON(json), sentence)
        XCTAssertEqual(SegmentReadyEventParser.formatListPreview(json), sentence)
    }

    func testCatalogPreview_clipsLongSentence() {
        let long = String(repeating: "甲", count: 200)
        let clipped = SegmentCatalogPreview.clip(long, maxChars: SegmentCatalogPreview.maxChars)
        XCTAssertEqual(clipped.count, SegmentCatalogPreview.maxChars)
        XCTAssertTrue(clipped.hasSuffix("…"))
    }

    func testSidebarSegmentItem_pendingWithoutChapterIsSegmentOnly() {
        let segment = SegmentRow(
            id: "s1", idx: 0, label: nil, chapter: nil, summary_status: "pending",
            summary_json: nil, raw_text: nil, translation: nil, anchor_label: nil,
            summary_provider: nil, summary_model: nil, summary_tier: nil, char_count: nil, retry_count: nil,
            summary_duration_s: nil, summary_llm_attempts: nil
        )
        let item = SidebarSegmentItem.make(from: segment)
        XCTAssertNil(item.title)
        XCTAssertEqual(item.headline, "段 1")
        XCTAssertNil(item.summaryPreview)
        XCTAssertNil(item.bulletLabelsLine)
    }

    func testSidebarSegmentItem_runningWithoutChapterIsSegmentOnly() {
        let segment = SegmentRow(
            id: "s1", idx: 0, label: nil, chapter: nil, summary_status: "running",
            summary_json: nil, raw_text: nil, translation: nil, anchor_label: nil,
            summary_provider: nil, summary_model: nil, summary_tier: nil, char_count: nil, retry_count: nil,
            summary_duration_s: nil, summary_llm_attempts: nil
        )
        let item = SidebarSegmentItem.make(from: segment)
        XCTAssertNil(item.title)
        XCTAssertEqual(item.headline, "段 1")
    }

    func testSidebarSegmentItem_pendingWithChapterUsesChapter() {
        let segment = SegmentRow(
            id: "s1", idx: 2, label: nil, chapter: "第二章", summary_status: "pending",
            summary_json: nil, raw_text: nil, translation: nil, anchor_label: nil,
            summary_provider: nil, summary_model: nil, summary_tier: nil, char_count: nil, retry_count: nil,
            summary_duration_s: nil, summary_llm_attempts: nil
        )
        let item = SidebarSegmentItem.make(from: segment)
        XCTAssertEqual(item.title, "第二章")
        XCTAssertEqual(item.headline, "段 3 · 第二章")
    }
}

final class SegmentCatalogPreviewArchitectureTests: XCTestCase {
    private func source(_ relativePath: String) throws -> String {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        return try String(
            contentsOf: macosRoot.appendingPathComponent(relativePath),
            encoding: .utf8
        )
    }

    func testCatalogRowsUseSlimPreviewAndFullWidth() throws {
        let reader = try source("Lumina/Features/Reader/ReaderView.swift")
        let models = try source("Lumina/Features/Reader/SegmentSidebarModels.swift")
        XCTAssertTrue(
            reader.contains("segment.summary_preview"),
            "the catalog must render GET /segments summary_preview for every row, not only hydrated neighbors"
        )
        XCTAssertTrue(
            reader.contains("segment.bullet_labels"),
            "the catalog must render GET /segments bullet_labels, not bullet bodies"
        )
        XCTAssertTrue(
            models.contains("SegmentCatalogPreview.previewLineLimit")
                || models.contains("lineLimit(1)"),
            "catalog summary and point titles must be single-line"
        )
        XCTAssertTrue(
            models.contains("truncationMode(.tail)"),
            "catalog lines must ellipsize at the row width instead of clipping to a few CJK glyphs"
        )
        XCTAssertTrue(
            reader.contains(".frame(maxWidth: .infinity, alignment: .leading)"),
            "catalog rows must take the cover width so LazyVStack does not propose a few-character width"
        )
        XCTAssertFalse(
            reader.contains("include_summary"),
            "opening the catalog must not pull full summary_json for the whole book"
        )
        XCTAssertFalse(
            reader.contains("scheduleSidebarPreview"),
            "the catalog must not hydrate summary_json just to stitch bullet bodies"
        )
        XCTAssertTrue(
            models.contains("SegmentCatalogHeadlineText.title"),
            "catalog first line must resolve title via chapter-then-label helper"
        )
        XCTAssertFalse(
            models.contains("TimelineView"),
            "catalog first line must not host live summarize captions"
        )
        let iconSlice = models.components(separatedBy: "private var statusIcon: some View").last ?? ""
        XCTAssertTrue(
            iconSlice.contains("Group {"),
            "statusIcon if/else must be wrapped in Group before .font; trailing .font on ViewBuilder if is a type-member error"
        )
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
            3_449
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
            3_366
        )
    }

    func testChunkTargetPresetsAndClamp() {
        XCTAssertEqual(ResegmentTarget.presets, [500, 1000, 1500, 2000, 2500])
        XCTAssertEqual(ResegmentTarget.clamp(50), 200)
        XCTAssertEqual(ResegmentTarget.clamp(3_449), 3_449)
        XCTAssertEqual(ResegmentTarget.clamp(9_000), 8_000)
        XCTAssertEqual(ResegmentTarget.clamp(5_000, range: 200...4000), 4_000)
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

    func testSummarizeActivityLabel_runningAndQueued() {
        let vm = ReaderViewModel()
        vm.summarizeState = "running"
        vm.segments = [
            SegmentRow(
                id: "s0", idx: 0, label: nil, chapter: nil, summary_status: "ready",
                summary_json: nil, raw_text: nil, translation: nil, anchor_label: nil,
                summary_provider: nil, summary_model: nil, summary_tier: nil, char_count: nil,
                retry_count: nil, summary_duration_s: nil, summary_llm_attempts: nil
            ),
            SegmentRow(
                id: "s1", idx: 1, label: nil, chapter: nil, summary_status: "running",
                summary_json: nil, raw_text: nil, translation: nil, anchor_label: nil,
                summary_provider: nil, summary_model: nil, summary_tier: nil, char_count: nil,
                retry_count: nil, summary_duration_s: nil, summary_llm_attempts: nil
            ),
            SegmentRow(
                id: "s2", idx: 2, label: nil, chapter: nil, summary_status: "pending",
                summary_json: nil, raw_text: nil, translation: nil, anchor_label: nil,
                summary_provider: nil, summary_model: nil, summary_tier: nil, char_count: nil,
                retry_count: nil, summary_duration_s: nil, summary_llm_attempts: nil
            ),
        ]
        XCTAssertEqual(vm.summarizeActivityLabel, "1 进行中 · 1 排队")
    }

    func testSegmentStatusRunning_promotesQueuedState() {
        let vm = ReaderViewModel()
        let core = CoreClient(baseURL: URL(string: "http://127.0.0.1:8765")!)
        vm.summarizeState = "queued"
        vm.segments = [
            SegmentRow(
                id: "s1", idx: 0, label: nil, chapter: nil, summary_status: "pending",
                summary_json: nil, raw_text: nil, translation: nil, anchor_label: nil,
                summary_provider: nil, summary_model: nil, summary_tier: nil, char_count: nil,
                retry_count: nil, summary_duration_s: nil, summary_llm_attempts: nil
            )
        ]
        vm.handleEvent(
            ["type": "segment_status", "idx": 0, "status": "running"],
            core: core
        )
        XCTAssertEqual(vm.summarizeState, "running")
        XCTAssertEqual(vm.summarizeActivityLabel, "1 进行中")
    }

    func testSettingsChunkTargetRange_allows200() {
        for kind in ModelProviderKind.allCases {
            XCTAssertEqual(kind.chunkTargetRange.lowerBound, 200)
            XCTAssertTrue(kind.chunkTargetRange.contains(200))
        }
    }

}
