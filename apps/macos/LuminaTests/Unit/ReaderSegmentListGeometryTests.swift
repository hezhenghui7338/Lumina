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

final class ReaderSegmentListPolicyTests: XCTestCase {
    func testExplicitClick_hiddenPinsWithoutPeek() {
        let next = ReaderSegmentListPolicy.toggleByExplicitClick(.hidden)
        XCTAssertTrue(next.pinned)
        XCTAssertFalse(next.peeking)
        XCTAssertTrue(next.inlineVisible)
        XCTAssertFalse(next.overlayVisible)
    }

    func testExplicitClick_peekingUpgradesToPinned() {
        let peeking = ReaderSegmentListVisibility(pinned: false, peeking: true)
        let next = ReaderSegmentListPolicy.toggleByExplicitClick(peeking)
        XCTAssertTrue(next.pinned)
        XCTAssertFalse(next.peeking)
        XCTAssertTrue(next.inlineVisible)
        XCTAssertFalse(next.overlayVisible)
    }

    func testExplicitClick_pinnedCloses() {
        let pinned = ReaderSegmentListVisibility(pinned: true, peeking: false)
        let next = ReaderSegmentListPolicy.toggleByExplicitClick(pinned)
        XCTAssertEqual(next, .hidden)
        XCTAssertFalse(next.anyVisible)
    }

    func testEndPeek_afterEdgePeekRetractsWithoutPinning() {
        let peeking = ReaderSegmentListPolicy.beginEdgePeek(.hidden)
        XCTAssertTrue(peeking.overlayVisible)
        XCTAssertFalse(peeking.pinned)
        let closed = ReaderSegmentListPolicy.endPeek(peeking)
        XCTAssertFalse(closed.peeking)
        XCTAssertFalse(closed.pinned)
        XCTAssertFalse(closed.anyVisible)
    }

    func testPinned_endPeekAndBeginEdgePeekDoNotUnpin() {
        let pinned = ReaderSegmentListVisibility(pinned: true, peeking: false)
        XCTAssertEqual(ReaderSegmentListPolicy.endPeek(pinned), pinned)
        XCTAssertEqual(ReaderSegmentListPolicy.beginEdgePeek(pinned), pinned)
        XCTAssertTrue(pinned.inlineVisible)
        XCTAssertFalse(pinned.overlayVisible)
    }

    func testHeaderPinAndClose() {
        let peeking = ReaderSegmentListVisibility(pinned: false, peeking: true)
        let pinned = ReaderSegmentListPolicy.pin(peeking)
        XCTAssertTrue(pinned.pinned)
        XCTAssertFalse(pinned.peeking)
        XCTAssertEqual(ReaderSegmentListPolicy.close(pinned), .hidden)
        XCTAssertEqual(ReaderSegmentListPolicy.close(peeking), .hidden)
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
}
