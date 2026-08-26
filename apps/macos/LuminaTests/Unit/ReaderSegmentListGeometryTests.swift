import CoreGraphics
import XCTest
@testable import Lumina

final class ReaderCoverPagePolicyTests: XCTestCase {
    func testToggle_opensSegmentsWithoutAnInlineColumn() {
        let next = ReaderCoverPagePolicy.toggle(.none, to: .segments)
        XCTAssertEqual(next, .segments)
        XCTAssertTrue(next.showsSegments)
        XCTAssertTrue(next.isOpen)
    }

    func testToggle_sameTargetCloses() {
        XCTAssertEqual(
            ReaderCoverPagePolicy.toggle(.segments, to: .segments),
            .none
        )
    }

    func testSelectItemAndClose_returnToReading() {
        XCTAssertEqual(ReaderCoverPagePolicy.selectItem(), .none)
        XCTAssertEqual(ReaderCoverPagePolicy.close(), .none)
        XCTAssertEqual(ReaderCoverPagePolicy.toggle(.none, to: .none), .none)
    }
}

final class ReaderCoverPageArchitectureTests: XCTestCase {
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

    func testReaderDoesNotSqueezeWithInlineSegmentColumn() throws {
        let reader = try source("Lumina/Features/Reader/ReaderView.swift")
        for banned in [
            "segmentListInlineVisible",
            "segmentListOverlayVisible",
            "segmentListPinned",
            "beginEdgePeek",
            "ReaderSegmentListPolicy",
            "frame(width: segmentsWidth)",
            "ReaderEdgeIcon",
            "EdgeHoverTracker",
            "handleEdgePointer",
        ] {
            XCTAssertFalse(reader.contains(banned), "\(banned) squeezes or peeks the reading surface")
        }
        XCTAssertTrue(
            reader.contains("ReaderCoverPageShell"),
            "segment list must overlay the feed without inserting a column"
        )
        XCTAssertTrue(reader.contains("toggleCoverPage(.segments)"))
    }

    func testReadingHasNoRecentsList() throws {
        let reader = try source("Lumina/Features/Reader/ReaderView.swift")
        let content = try source("Lumina/ContentView.swift")
        for banned in ["LibraryRecentsView", "展开最近阅读", "toggleCoverPage(.recents)"] {
            XCTAssertFalse(reader.contains(banned), "\(banned) brings back the reading recents list")
            XCTAssertFalse(content.contains(banned), "\(banned) brings back the reading recents list")
        }
        XCTAssertFalse(content.contains("recentsWidth"))
        XCTAssertFalse(reader.contains("sidebar.left"))
    }

    func testSegmentCoverSlidesFromBottomAboveTheBottomBar() throws {
        let reader = try source("Lumina/Features/Reader/ReaderView.swift")
        let layout = readerLayoutSource(reader)
        let coverBlock = coverPageBlock(layout)

        XCTAssertTrue(
            coverBlock.contains("ReaderCoverPageShell"),
            "the catalog must still be a cover overlay"
        )
        XCTAssertTrue(
            coverBlock.contains(".move(edge: .bottom)"),
            "the catalog must slide up from the bottom"
        )
        XCTAssertFalse(
            coverBlock.contains(".move(edge: .top)"),
            "the catalog must not slide in from the top"
        )
        XCTAssertTrue(
            coverBlock.contains(".padding(.bottom, ReaderChromeBarMetrics.height)"),
            "the catalog must sit above the bottom bar"
        )
        XCTAssertFalse(
            coverBlock.contains("zIndex(1)"),
            "zIndex(1) covers the bottom bar so the catalog toggle cannot be reached"
        )

        guard
            let coverRange = layout.range(of: "ReaderCoverPageShell"),
            let bottomRange = layout.range(of: "readerBottomBarOverlay")
        else {
            return XCTFail("readerLayout must host both the catalog shell and the bottom bar")
        }
        XCTAssertLessThan(
            coverRange.lowerBound,
            bottomRange.lowerBound,
            "the bottom bar must be above the catalog in ZStack order"
        )
    }

    func testBarsStayVisibleWhileSegmentCoverIsOpen() throws {
        let reader = try source("Lumina/Features/Reader/ReaderView.swift")
        let after = reader.components(separatedBy: "private var barsVisible: Bool").last ?? ""
        let body = after.components(separatedBy: "private var librarySummarizeOverviewActive").first ?? ""
        XCTAssertTrue(
            body.contains("coverPage != .none") || body.contains("coverPage.isOpen"),
            "the bottom bar must stay up while the catalog is open so it can close it"
        )
    }

    func testOpeningOverlayClosesSegmentCover() throws {
        let reader = try source("Lumina/Features/Reader/ReaderView.swift")
        let after = reader.components(separatedBy: "private func openOverlay").last ?? ""
        let body = after.components(separatedBy: "private func toggleOverlay").first ?? ""
        XCTAssertTrue(
            body.contains("ReaderCoverPagePolicy.close()"),
            "notes/chat must dismiss the catalog now that the bottom bar stays tappable"
        )
    }

    func testCoverShellHasNoBackButton() throws {
        let shell = try source("Lumina/Features/Reader/ReaderChromeClickPolicy.swift")
        guard let start = shell.range(of: "struct ReaderCoverPageShell"),
              let end = shell.range(of: "enum LuminaBodyTextClickOutcome")
        else {
            return XCTFail("could not isolate ReaderCoverPageShell")
        }
        let body = String(shell[start.lowerBound..<end.lowerBound])
        XCTAssertFalse(body.contains("返回"), "the catalog must close from the bottom bar, not a back button")
        XCTAssertFalse(body.contains("chevron.down"))
        XCTAssertFalse(body.contains("onBack"))
        XCTAssertFalse(body.contains("返回阅读"))
        XCTAssertTrue(body.contains("LuminaTheme.background"))
    }

    private func readerLayoutSource(_ reader: String) -> String {
        let after = reader.components(separatedBy: "private var readerLayout: some View").last ?? ""
        return after.components(separatedBy: ".onExitCommand { handleExitCommand() }").first ?? ""
    }

    private func coverPageBlock(_ layout: String) -> String {
        let after = layout.components(separatedBy: "if coverPage == .segments").last ?? ""
        return after.components(separatedBy: "if barsVisible").first ?? ""
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

    func testShouldCommitMeasurementIgnoresSubPointJitter() {
        XCTAssertFalse(
            ReaderSegmentPanelHeight.shouldCommitMeasurement(current: 240, incoming: 240.4)
        )
        XCTAssertTrue(
            ReaderSegmentPanelHeight.shouldCommitMeasurement(current: 240, incoming: 242)
        )
        XCTAssertFalse(
            ReaderSegmentPanelHeight.shouldCommitMeasurement(current: 240, incoming: 0)
        )
    }
}

final class ReadingProgressTests: XCTestCase {
    func testRestoreIndex_prefersLocalWhenSegmentCountMatches() {
        XCTAssertEqual(
            ReadingProgress.restoreIndex(
                serverIndex: 1,
                localIndex: 6,
                localSegmentCount: 10,
                currentSegmentCount: 10
            ),
            6
        )
    }

    func testRestoreIndex_ignoresLocalAfterResegment() {
        XCTAssertEqual(
            ReadingProgress.restoreIndex(
                serverIndex: 0,
                localIndex: 8,
                localSegmentCount: 12,
                currentSegmentCount: 4
            ),
            0
        )
    }

    func testRestoreIndex_clampsLocalToCurrentCount() {
        XCTAssertEqual(
            ReadingProgress.restoreIndex(
                serverIndex: 0,
                localIndex: 99,
                localSegmentCount: 10,
                currentSegmentCount: 10
            ),
            9
        )
    }

    func testEndPinSpacerHeight_letsLastSegmentReachTop() {
        XCTAssertEqual(ReadingProgress.endPinSpacerHeight(viewportHeight: 800), 736)
        XCTAssertEqual(ReadingProgress.endPinSpacerHeight(viewportHeight: 0), 120)
        XCTAssertEqual(ReadingProgress.endPinSpacerHeight(viewportHeight: 80), 120)
    }

    func testPeekingLastSegmentIsNotFinished() {
        // Only the segment pinned to the top counts. Seeing the last segment at
        // the bottom of the screen must not mark the book finished.
        XCTAssertFalse(ReadingProgress.isFinished(index: 7, count: 10))
        XCTAssertEqual(
            ReadingProgress.statusLabel(opened: true, index: 7, segmentCount: 10),
            "在读 · 8/10 段"
        )
    }

    func testPercent_usesSegmentIndexOnly() {
        let percent = ReadingProgress.percent(index: 4, count: 10)
        XCTAssertEqual(percent, 0.40, accuracy: 0.0001)
        XCTAssertEqual(
            ReadingProgress.statusLabel(opened: true, index: 4, segmentCount: 10),
            "在读 · 5/10 段"
        )
    }

    func testPercent_lastSegmentIsFinished() {
        let percent = ReadingProgress.percent(index: 9, count: 10)
        XCTAssertEqual(percent, 1.0, accuracy: 0.0001)
        XCTAssertTrue(ReadingProgress.isFinished(index: 9, count: 10))
        XCTAssertEqual(
            ReadingProgress.statusLabel(opened: true, index: 9, segmentCount: 10),
            "已读完"
        )
    }

    func testPercent_singleSegmentStaysReading() {
        XCTAssertEqual(ReadingProgress.percent(index: 0, count: 1), 0, accuracy: 0.0001)
        XCTAssertFalse(ReadingProgress.isFinished(index: 0, count: 1))
        XCTAssertEqual(
            ReadingProgress.statusLabel(opened: true, index: 0, segmentCount: 1),
            "在读 · 1/1 段"
        )
    }

    func testStatusLabel_usesSegmentIndexNotPercent() {
        XCTAssertEqual(
            ReadingProgress.statusLabel(opened: false, index: 4, segmentCount: 10),
            "未读"
        )
        XCTAssertEqual(
            ReadingProgress.statusLabel(opened: true, index: 0, segmentCount: 10),
            "在读 · 1/10 段"
        )
        XCTAssertEqual(
            ReadingProgress.statusLabel(opened: true, index: 4, segmentCount: 10),
            "在读 · 5/10 段"
        )
        XCTAssertEqual(
            ReadingProgress.statusLabel(opened: true, index: 8, segmentCount: 10),
            "在读 · 9/10 段"
        )
        XCTAssertEqual(
            ReadingProgress.statusLabel(opened: true, index: 9, segmentCount: 10),
            "已读完"
        )
    }

    func testRestorePinsSegmentStart_notPixelOffset() {
        // The persisted position is a segment index and nothing else, so a
        // resume can never land mid-segment or drift with layout.
        let cached = ReaderPreferences.CachedProgress(index: 6, segmentCount: 10)
        let encoded = try? JSONEncoder().encode(cached)
        let json = encoded.flatMap { String(data: $0, encoding: .utf8) } ?? ""
        XCTAssertFalse(json.contains("offsetY"))
        XCTAssertEqual(
            ReadingProgress.restoreIndex(
                serverIndex: 1,
                localIndex: 6,
                localSegmentCount: 10,
                currentSegmentCount: 10
            ),
            6
        )
    }

    func testCachedProgressDecodesLegacyPayloadWithoutOffset() throws {
        // Legacy caches carried pixel offsets and a content mode. Both are
        // ignored now; only the segment index survives.
        let legacy = Data(#"{"index":5,"segmentCount":12,"offsetY":88,"contentMode":"original"}"#.utf8)
        let decoded = try JSONDecoder().decode(ReaderPreferences.CachedProgress.self, from: legacy)
        XCTAssertEqual(decoded.index, 5)
        XCTAssertEqual(decoded.segmentCount, 12)

        let modern = Data(#"{"index":5,"segmentCount":12}"#.utf8)
        XCTAssertEqual(
            try JSONDecoder().decode(ReaderPreferences.CachedProgress.self, from: modern),
            decoded
        )
    }

    func testProgressPhase_onlyReadingRecords() {
        XCTAssertFalse(ReaderProgressPhase.restoring.recordsProgress)
        XCTAssertTrue(ReaderProgressPhase.reading.recordsProgress)
    }
}

@MainActor
final class ReadingProgressStoreTests: XCTestCase {
    private var bookIds: [String] = []

    private func makeBookId() -> String {
        let id = "test-book-\(UUID().uuidString)"
        bookIds.append(id)
        return id
    }

    override func tearDown() {
        let ids = bookIds
        bookIds = []
        Task { @MainActor in
            for id in ids {
                ReadingProgressStore.shared.forget(bookId: id)
            }
        }
        super.tearDown()
    }

    func testRecord_persistsSegmentIndexImmediately() {
        let book = makeBookId()
        let store = ReadingProgressStore.shared
        store.record(bookId: book, index: 5, total: 20)

        XCTAssertEqual(store.position(for: book)?.index, 5)
        XCTAssertEqual(store.position(for: book)?.total, 20)
        XCTAssertEqual(ReaderPreferences.cachedProgress(for: book)?.index, 5)
    }

    func testRecord_clampsToLastSegment() {
        let book = makeBookId()
        let store = ReadingProgressStore.shared
        store.record(bookId: book, index: 99, total: 10)
        XCTAssertEqual(store.position(for: book)?.index, 9)

        store.record(bookId: book, index: -3, total: 10)
        XCTAssertEqual(store.position(for: book)?.index, 0)
    }

    /// Switching books from the sidebar used to mix two books' positions
    /// because the pending write was a single scalar.
    func testRecord_keepsBooksIndependentWhenSwitching() {
        let bookA = makeBookId()
        let bookB = makeBookId()
        let store = ReadingProgressStore.shared

        store.record(bookId: bookA, index: 5, total: 20)
        store.record(bookId: bookB, index: 12, total: 40)
        store.record(bookId: bookB, index: 13, total: 40)

        XCTAssertEqual(store.position(for: bookA)?.index, 5)
        XCTAssertEqual(store.position(for: bookB)?.index, 13)
        XCTAssertEqual(ReaderPreferences.cachedProgress(for: bookA)?.index, 5)
        XCTAssertEqual(ReaderPreferences.cachedProgress(for: bookB)?.index, 13)
    }

    /// Reading further in a second book must not roll the first one back when
    /// the reader returns to it.
    func testResumeIndex_returnsEachBookToItsOwnSegment() {
        let bookA = makeBookId()
        let bookB = makeBookId()
        let store = ReadingProgressStore.shared

        store.record(bookId: bookA, index: 5, total: 20)
        store.record(bookId: bookB, index: 13, total: 40)

        XCTAssertEqual(
            store.resumeIndex(bookId: bookA, serverIndex: 0, segmentCount: 20),
            5
        )
        XCTAssertEqual(
            store.resumeIndex(bookId: bookB, serverIndex: 0, segmentCount: 40),
            13
        )
    }

    func testResumeIndex_fallsBackToServerAfterResegment() {
        let book = makeBookId()
        let store = ReadingProgressStore.shared
        store.record(bookId: book, index: 30, total: 40)

        XCTAssertEqual(
            store.resumeIndex(bookId: book, serverIndex: 2, segmentCount: 8),
            2
        )
    }

    func testForget_dropsLocalRecordSoResegmentStartsClean() {
        let book = makeBookId()
        let store = ReadingProgressStore.shared
        store.record(bookId: book, index: 7, total: 20)
        store.forget(bookId: book)

        XCTAssertNil(store.position(for: book))
        XCTAssertNil(ReaderPreferences.cachedProgress(for: book))
    }

    func testHydrate_adoptsServerPositionWithoutLosingIt() {
        let book = makeBookId()
        let store = ReadingProgressStore.shared
        store.hydrate(bookId: book, index: 4, total: 12)

        XCTAssertEqual(store.position(for: book)?.index, 4)
        XCTAssertEqual(store.position(for: book)?.total, 12)
    }
}

/// Locks the architecture that fixed progress drift: SwiftUI's `scrollPosition`
/// is the only thing allowed to anchor the feed, and the pinned segment is the
/// only source of progress. A second anchor writer (AppKit nudging the scroll
/// origin) or geometry-derived progress is what made this break repeatedly.
final class ReaderProgressArchitectureTests: XCTestCase {
    private func readerSource() throws -> String {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()  // Unit
            .deletingLastPathComponent()  // LuminaTests
            .deletingLastPathComponent()  // macos
        let reader = macosRoot
            .appendingPathComponent("Lumina/Features/Reader/ReaderView.swift")
        return try String(contentsOf: reader, encoding: .utf8)
    }

    func testReaderHasNoViewportGeometryFallback() throws {
        let source = try readerSource()
        for banned in [
            "viewportAnchor",
            "SegmentFeedFrameKey",
            "FeedVisibleTopKey",
            "onFeedVisibleTopChange",
            "visibleTopInFeed",
            "heightGrowthAboveVisibleTop",
        ] {
            XCTAssertFalse(
                source.contains(banned),
                "\(banned) reintroduces geometry-derived reading progress"
            )
        }
    }

    func testReaderHasSingleScrollAnchorOwner() throws {
        let source = try readerSource()
        for banned in ["adjustOrigin", "applyScrollOriginOnce", "applyFeedVisibleTop"] {
            XCTAssertFalse(
                source.contains(banned),
                "\(banned) makes AppKit a second scroll anchor owner"
            )
        }
        XCTAssertEqual(
            source.components(separatedBy: ".scrollPosition(id:").count - 1,
            1,
            "the reader feed must have exactly one scrollPosition binding"
        )
    }
}

final class ReaderKeyboardScrollTests: XCTestCase {
    func testClampedOriginYStopsAtTopAndBottom() {
        XCTAssertEqual(
            ReaderKeyboardScroll.clampedOriginY(
                currentY: 10,
                deltaY: -80,
                viewportHeight: 400,
                contentHeight: 1200
            ),
            0
        )
        XCTAssertEqual(
            ReaderKeyboardScroll.clampedOriginY(
                currentY: 790,
                deltaY: 80,
                viewportHeight: 400,
                contentHeight: 1200
            ),
            800
        )
    }

    func testClampedOriginYMovesByLineDelta() {
        XCTAssertEqual(
            ReaderKeyboardScroll.clampedOriginY(
                currentY: 200,
                deltaY: ReaderKeyboardScroll.lineDelta,
                viewportHeight: 400,
                contentHeight: 1200
            ),
            280
        )
    }

    func testPageDeltaUsesNinetyPercentOfViewport() {
        XCTAssertEqual(ReaderKeyboardScroll.pageDelta(viewportHeight: 400, page: 1), 360)
        XCTAssertEqual(ReaderKeyboardScroll.pageDelta(viewportHeight: 400, page: -1), -360)
        XCTAssertEqual(ReaderKeyboardScroll.pageDelta(viewportHeight: 80, page: 1), 120)
    }

    func testCanMoveRespectsEdges() {
        XCTAssertTrue(ReaderKeyboardScroll.canMove(originY: 0, deltaY: 80, maxY: 800))
        XCTAssertFalse(ReaderKeyboardScroll.canMove(originY: 0, deltaY: -80, maxY: 800))
        XCTAssertTrue(ReaderKeyboardScroll.canMove(originY: 800, deltaY: -80, maxY: 800))
        XCTAssertFalse(ReaderKeyboardScroll.canMove(originY: 800, deltaY: 80, maxY: 800))
        XCTAssertFalse(ReaderKeyboardScroll.canMove(originY: 100, deltaY: 0, maxY: 800))
    }
}

final class SegmentTurnNavigationTests: XCTestCase {
    func testMiddleGoesPrevAndNext() {
        XCTAssertEqual(
            SegmentTurnNavigation.targetIdx(current: 2, delta: -1, sortedIdxs: [0, 2, 5]),
            0
        )
        XCTAssertEqual(
            SegmentTurnNavigation.targetIdx(current: 2, delta: 1, sortedIdxs: [0, 2, 5]),
            5
        )
    }

    func testFirstHasNoPrev() {
        XCTAssertNil(
            SegmentTurnNavigation.targetIdx(current: 0, delta: -1, sortedIdxs: [0, 2, 5])
        )
    }

    func testLastHasNoNext() {
        XCTAssertNil(
            SegmentTurnNavigation.targetIdx(current: 5, delta: 1, sortedIdxs: [0, 2, 5])
        )
    }

    func testEmptyAndMissingCurrentReturnNil() {
        XCTAssertNil(SegmentTurnNavigation.targetIdx(current: 0, delta: 1, sortedIdxs: []))
        XCTAssertNil(
            SegmentTurnNavigation.targetIdx(current: 9, delta: 1, sortedIdxs: [0, 2, 5])
        )
    }
}

final class SegmentTurnKeyPolicyTests: XCTestCase {
    func testUnshiftedBracketsTurnEveryPress() {
        XCTAssertEqual(
            SegmentTurnKeyPolicy.delta(
                keyCode: SegmentTurnKeyPolicy.openBracketKeyCode,
                characters: "[",
                shift: false,
                isRepeat: false
            ),
            -1
        )
        XCTAssertEqual(
            SegmentTurnKeyPolicy.delta(
                keyCode: SegmentTurnKeyPolicy.closeBracketKeyCode,
                characters: "]",
                shift: false,
                isRepeat: false
            ),
            1
        )
        XCTAssertEqual(
            SegmentTurnKeyPolicy.delta(
                keyCode: SegmentTurnKeyPolicy.openBracketKeyCode,
                characters: "【",
                shift: false,
                isRepeat: false
            ),
            -1,
            "Chinese IME 【 is the same key as [ and must keep turning on later presses"
        )
        XCTAssertEqual(
            SegmentTurnKeyPolicy.delta(
                keyCode: SegmentTurnKeyPolicy.closeBracketKeyCode,
                characters: "】",
                shift: false,
                isRepeat: false
            ),
            1
        )
    }

    func testShiftAndRepeatDoNotTurn() {
        XCTAssertNil(
            SegmentTurnKeyPolicy.delta(
                keyCode: SegmentTurnKeyPolicy.openBracketKeyCode,
                characters: "{",
                shift: true,
                isRepeat: false
            )
        )
        XCTAssertNil(
            SegmentTurnKeyPolicy.delta(
                keyCode: SegmentTurnKeyPolicy.closeBracketKeyCode,
                characters: "]",
                shift: false,
                isRepeat: true
            )
        )
    }

    func testFullwidthCharactersStillTurnWithoutKnownKeyCode() {
        XCTAssertEqual(
            SegmentTurnKeyPolicy.delta(
                keyCode: 0,
                characters: "【",
                shift: false,
                isRepeat: false
            ),
            -1
        )
        XCTAssertEqual(
            SegmentTurnKeyPolicy.delta(
                keyCode: 0,
                characters: "】",
                shift: false,
                isRepeat: false
            ),
            1
        )
    }

    func testReaderTurnsSegmentsFromKeyMonitorNotFocusState() throws {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let reader = try String(
            contentsOf: macosRoot.appendingPathComponent("Lumina/Features/Reader/ReaderView.swift"),
            encoding: .utf8
        )
        XCTAssertFalse(
            reader.contains(".onKeyPress(\"[\")") || reader.contains(".onKeyPress(\"【\")"),
            "character onKeyPress dies after selectable body text steals first responder"
        )
        XCTAssertTrue(
            reader.contains("SegmentTurnKeyPolicy.delta"),
            "hardware [ ] / 【】 must be handled in the existing keyDown monitor so every press turns"
        )
        XCTAssertTrue(
            reader.contains("onTurnSegment"),
            "the key monitor must call back into navigateSegment"
        )
        XCTAssertTrue(
            reader.contains("LuminaSelectableTextView { return false }"),
            "selectable body text must not be treated as an editor or [ ] would be ignored"
        )
    }
}

final class LuminaTextLayoutSizingTests: XCTestCase {
    func testNarrowWidthDoesNotEnsureLayout() {
        XCTAssertFalse(LuminaTextLayoutSizing.shouldEnsureLayout(containerWidth: 0))
        XCTAssertFalse(LuminaTextLayoutSizing.shouldEnsureLayout(containerWidth: 7))
        XCTAssertTrue(LuminaTextLayoutSizing.shouldEnsureLayout(containerWidth: 8))
        XCTAssertNil(LuminaTextLayoutSizing.layoutWidth(for: 0))
        XCTAssertEqual(LuminaTextLayoutSizing.layoutWidth(for: 640), 640)
    }

    func testNarrowWidthUsesPlaceholderHeightNotGlyphCount() {
        XCTAssertEqual(
            LuminaTextLayoutSizing.intrinsicHeight(usedRectHeight: 12_000, containerWidth: 0),
            LuminaTextLayoutSizing.placeholderHeight
        )
        XCTAssertEqual(
            LuminaTextLayoutSizing.intrinsicHeight(usedRectHeight: 120.2, containerWidth: 400),
            121
        )
    }

    func testWidthDidChangeIgnoresSubPointJitter() {
        XCTAssertFalse(LuminaTextLayoutSizing.widthDidChange(from: 400, to: 400.2))
        XCTAssertTrue(LuminaTextLayoutSizing.widthDidChange(from: 400, to: 401))
    }

    func testContainerLayoutDoesNotUnconditionallyInvalidate() throws {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let source = try String(
            contentsOf: macosRoot.appendingPathComponent(
                "Lumina/Features/Shared/SelectableTextView.swift"
            ),
            encoding: .utf8
        )
        guard let start = source.range(of: "final class IntrinsicSizingTextContainer"),
              let layoutRange = source.range(of: "override func layout()", range: start.lowerBound..<source.endIndex)
        else {
            return XCTFail("could not isolate IntrinsicSizingTextContainer.layout()")
        }
        let layout = String(source[layoutRange.lowerBound...])
            .components(separatedBy: "override var intrinsicContentSize").first ?? ""
        XCTAssertTrue(layout.contains("widthDidChange"))
        XCTAssertTrue(layout.contains("invalidate: widthChanged"))
        XCTAssertFalse(
            layout.contains("invalidate: true"),
            "layout() must not invalidate CJK intrinsic height unless width actually changed"
        )
    }
}

final class SegmentSummaryPlaceholderHeightTests: XCTestCase {
    func testReserved_usesFloorWhenCharCountMissing() {
        XCTAssertEqual(SegmentSummaryPlaceholderHeight.reserved(charCount: nil), 200)
        XCTAssertEqual(SegmentSummaryPlaceholderHeight.reserved(charCount: 0), 200)
        XCTAssertEqual(SegmentSummaryPlaceholderHeight.reserved(charCount: 100), 200)
    }

    func testReserved_scalesThenCaps() {
        XCTAssertEqual(SegmentSummaryPlaceholderHeight.reserved(charCount: 1_200), 200)
        XCTAssertEqual(SegmentSummaryPlaceholderHeight.reserved(charCount: 2_400), 400)
        XCTAssertEqual(SegmentSummaryPlaceholderHeight.reserved(charCount: 10_000), 600)
    }

    func testLoadingAndRunningShareReservedHeight() {
        let count = 3_000
        let reserved = SegmentSummaryPlaceholderHeight.reserved(charCount: count)
        XCTAssertEqual(reserved, 500)
        XCTAssertGreaterThan(reserved, 1, "running must not collapse to EmptyView height")
    }

    func testSegmentBlock_runningUsesReservedSkeletonNotEmptyView() throws {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let source = try String(
            contentsOf: macosRoot.appendingPathComponent(
                "Lumina/Features/Reader/SegmentReadingBlock.swift"
            ),
            encoding: .utf8
        )
        XCTAssertTrue(source.contains("SegmentSummaryPlaceholderHeight.reserved"))
        XCTAssertTrue(source.contains("isSummaryLoading || segment.summary_status == \"running\""))
        XCTAssertFalse(
            source.contains("case \"running\":"),
            "running must share the loading skeleton, not a collapsing placeholder branch"
        )
        XCTAssertFalse(source.contains("EmptyView()"))
        XCTAssertTrue(source.contains("progressLabel("))
        XCTAssertTrue(source.contains(".minimumScaleFactor(0.8)"))
    }
}
