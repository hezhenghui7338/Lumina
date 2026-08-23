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
    func testSaveIndex_usesVisibleUntilLast() {
        XCTAssertEqual(
            ReadingProgress.saveIndex(visibleIndex: 7, lastIndex: 9),
            7
        )
        XCTAssertEqual(
            ReadingProgress.saveIndex(visibleIndex: 9, lastIndex: 9),
            9
        )
        XCTAssertEqual(
            ReadingProgress.saveIndex(visibleIndex: 12, lastIndex: 9),
            9
        )
    }

    func testSaveIndex_doesNotSnapBackToLastWhenScrollingEarlier() {
        XCTAssertEqual(
            ReadingProgress.saveIndex(visibleIndex: 3, lastIndex: 9),
            3
        )
    }

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
        // Top-pinned segment 7 of 10 remains 在读; finished only when index is last.
        let visible = ReadingProgress.saveIndex(visibleIndex: 7, lastIndex: 9)
        XCTAssertEqual(visible, 7)
        XCTAssertNotEqual(visible, 9)
    }

    func testCachedProgressCodable() throws {
        let cached = ReaderPreferences.CachedProgress(index: 4, segmentCount: 10, offsetY: 88)
        let data = try JSONEncoder().encode(cached)
        let decoded = try JSONDecoder().decode(ReaderPreferences.CachedProgress.self, from: data)
        XCTAssertEqual(decoded.index, 4)
        XCTAssertEqual(decoded.segmentCount, 10)
        XCTAssertEqual(decoded.offsetY, 88)
    }

    func testCachedProgressDecodesLegacyPayloadWithoutOffset() throws {
        let data = Data(#"{"index":5,"segmentCount":12}"#.utf8)
        let decoded = try JSONDecoder().decode(ReaderPreferences.CachedProgress.self, from: data)
        XCTAssertEqual(decoded.index, 5)
        XCTAssertEqual(decoded.segmentCount, 12)
        XCTAssertEqual(decoded.offsetY, 0)
    }

    func testViewportAnchor_usesFeedFramesNotStaleScrollPosition() {
        // After chrome/layout preserve, SwiftUI scrollPosition is niled; progress
        // must still follow the segment currently at the viewport top.
        let frames: [Int: CGRect] = [
            2: CGRect(x: 0, y: 0, width: 400, height: 300),
            5: CGRect(x: 0, y: 312, width: 400, height: 500),
            6: CGRect(x: 0, y: 824, width: 400, height: 400),
        ]
        let anchor = ReadingProgress.viewportAnchor(visibleTop: 500, frames: frames)
        XCTAssertEqual(anchor?.index, 5)
        XCTAssertEqual(anchor?.offsetY ?? -1, 188, accuracy: 0.01)
    }

    func testViewportAnchor_doesNotStickToEarlierSegment() {
        let frames: [Int: CGRect] = [
            0: CGRect(x: 0, y: 0, width: 400, height: 400),
            1: CGRect(x: 0, y: 412, width: 400, height: 400),
            2: CGRect(x: 0, y: 824, width: 400, height: 400),
        ]
        let anchor = ReadingProgress.viewportAnchor(visibleTop: 900, frames: frames)
        XCTAssertEqual(anchor?.index, 2)
        XCTAssertEqual(anchor?.offsetY ?? -1, 76, accuracy: 0.01)
    }

    func testRestoreOffsetY_keepsOffsetUntilResegment() {
        XCTAssertEqual(
            ReadingProgress.restoreOffsetY(
                localOffsetY: 120,
                localSegmentCount: 10,
                currentSegmentCount: 10
            ),
            120
        )
        XCTAssertEqual(
            ReadingProgress.restoreOffsetY(
                localOffsetY: 120,
                localSegmentCount: 12,
                currentSegmentCount: 4
            ),
            0
        )
        XCTAssertEqual(
            ReadingProgress.restoreOffsetY(
                localOffsetY: nil,
                localSegmentCount: 10,
                currentSegmentCount: 10
            ),
            0
        )
    }

    func testViewportAnchor_returnsNilWhenVisibleTopOutsideIncompleteFrames() {
        // LazyVStack rematerializing from the start only reports segment 0.
        // A mid-book visibleTop must not snap to home.
        let frames: [Int: CGRect] = [
            0: CGRect(x: 0, y: 0, width: 400, height: 400),
        ]
        XCTAssertNil(
            ReadingProgress.viewportAnchor(visibleTop: 50_000, frames: frames)
        )
        XCTAssertEqual(
            ReadingProgress.viewportAnchor(visibleTop: 10, frames: frames)?.index,
            0
        )
    }

    func testViewportAnchor_hitsContainedMiddleSegment() {
        let frames: [Int: CGRect] = [
            48: CGRect(x: 0, y: 4800, width: 400, height: 400),
            49: CGRect(x: 0, y: 5212, width: 400, height: 400),
            50: CGRect(x: 0, y: 5624, width: 400, height: 400),
        ]
        let anchor = ReadingProgress.viewportAnchor(visibleTop: 5300, frames: frames)
        XCTAssertEqual(anchor?.index, 49)
        XCTAssertEqual(anchor?.offsetY ?? -1, 88, accuracy: 0.01)
    }

    func testShouldCommitProgress_rejectsUnconfirmedJumpToZero() {
        XCTAssertFalse(
            ReadingProgress.shouldCommitProgress(
                previousIndex: 20,
                nextIndex: 0,
                hitContained: false
            )
        )
    }

    func testShouldCommitProgress_allowsConfirmedScrollToStart() {
        XCTAssertTrue(
            ReadingProgress.shouldCommitProgress(
                previousIndex: 20,
                nextIndex: 0,
                hitContained: true
            )
        )
        XCTAssertTrue(
            ReadingProgress.shouldCommitProgress(
                previousIndex: 0,
                nextIndex: 0,
                hitContained: false
            )
        )
    }

    func testShouldReplaceCachedIndex_rejectsUnconfirmedZeroOverMidCache() {
        XCTAssertFalse(
            ReadingProgress.shouldReplaceCachedIndex(
                cachedIndex: 18,
                cachedSegmentCount: 40,
                nextIndex: 0,
                nextSegmentCount: 40,
                confirmedHit: false
            )
        )
        XCTAssertTrue(
            ReadingProgress.shouldReplaceCachedIndex(
                cachedIndex: 18,
                cachedSegmentCount: 40,
                nextIndex: 0,
                nextSegmentCount: 12,
                confirmedHit: false
            )
        )
        XCTAssertTrue(
            ReadingProgress.shouldReplaceCachedIndex(
                cachedIndex: 18,
                cachedSegmentCount: 40,
                nextIndex: 0,
                nextSegmentCount: 40,
                confirmedHit: true
            )
        )
    }

    func testShouldApplyRestoredOrigin_skipsWhenContentTooShort() {
        XCTAssertFalse(
            ReadingProgress.shouldApplyRestoredOrigin(targetY: 12_000, maxY: 200)
        )
        XCTAssertTrue(
            ReadingProgress.shouldApplyRestoredOrigin(targetY: 12_000, maxY: 12_000)
        )
        XCTAssertTrue(
            ReadingProgress.shouldApplyRestoredOrigin(targetY: 0, maxY: 0)
        )
    }

    func testRestoreOffsetY_zerosWhenContentModeChanges() {
        XCTAssertEqual(
            ReadingProgress.restoreOffsetY(
                localOffsetY: 120,
                localSegmentCount: 10,
                currentSegmentCount: 10,
                localContentMode: "summary",
                currentContentMode: "original"
            ),
            0
        )
        XCTAssertEqual(
            ReadingProgress.restoreOffsetY(
                localOffsetY: 120,
                localSegmentCount: 10,
                currentSegmentCount: 10,
                localContentMode: "summary",
                currentContentMode: "summary"
            ),
            120
        )
        XCTAssertEqual(
            ReadingProgress.restoreOffsetY(
                localOffsetY: 120,
                localSegmentCount: 10,
                currentSegmentCount: 10,
                localContentMode: nil,
                currentContentMode: "summary"
            ),
            120
        )
    }

    func testRestoredOriginY_requiresTargetFrame() {
        let frames: [Int: CGRect] = [
            4: CGRect(x: 0, y: 1600, width: 400, height: 400),
        ]
        XCTAssertNil(
            ReadingProgress.restoredOriginY(index: 8, offsetY: 40, frames: frames)
        )
        XCTAssertEqual(
            ReadingProgress.restoredOriginY(index: 4, offsetY: 40, frames: frames),
            1640
        )
        XCTAssertFalse(
            ReadingProgress.canApplyRestore(
                index: 4,
                offsetY: 40,
                frames: frames,
                maxY: 200
            )
        )
        XCTAssertTrue(
            ReadingProgress.canApplyRestore(
                index: 4,
                offsetY: 40,
                frames: frames,
                maxY: 1640
            )
        )
    }

    func testRestoreAttempt_waitsWithoutFrameThenAppliesOnce() {
        var attempt = ReaderRestoreAttempt(index: 5, offsetY: 80)
        let empty: [Int: CGRect] = [:]
        XCTAssertEqual(attempt.step(frames: empty, maxY: 10_000), .waiting)

        let frames: [Int: CGRect] = [
            5: CGRect(x: 0, y: 2000, width: 400, height: 400),
        ]
        XCTAssertEqual(attempt.step(frames: frames, maxY: 10_000), .apply(2080))
        attempt.markApplied()
        XCTAssertEqual(attempt.step(frames: frames, maxY: 10_000), .finished)
    }

    func testRestoreAttempt_retriesOnceWhenContentTooShortThenFinishes() {
        var attempt = ReaderRestoreAttempt(index: 5, offsetY: 80)
        let frames: [Int: CGRect] = [
            5: CGRect(x: 0, y: 2000, width: 400, height: 400),
        ]
        XCTAssertEqual(attempt.step(frames: frames, maxY: 100), .waiting)
        XCTAssertTrue(attempt.retryUsed)
        XCTAssertEqual(attempt.step(frames: frames, maxY: 100), .finished)
    }

    func testRestoreAttempt_skipsOriginWhenOffsetIsTiny() {
        var attempt = ReaderRestoreAttempt(index: 2, offsetY: 0.5)
        XCTAssertEqual(attempt.step(frames: [:], maxY: 0), .finished)
    }

    func testJumpingPhase_cancelsOriginRestore() {
        XCTAssertTrue(ReaderScrollPhase.jumping.cancelsOriginRestore)
        XCTAssertFalse(ReaderScrollPhase.tracking.allowsProgressSave == false)
        XCTAssertTrue(ReaderScrollPhase.tracking.allowsProgressSave)
        XCTAssertFalse(ReaderScrollPhase.restoring.allowsProgressSave)
        XCTAssertFalse(ReaderScrollPhase.jumping.allowsProgressSave)
        XCTAssertFalse(ReaderScrollPhase.preserving.allowsViewportDrivenSelection)
    }

    func testHeightGrowthAboveVisibleTop_onlyCountsSegmentsFullyAbove() {
        let previous: [Int: CGRect] = [
            0: CGRect(x: 0, y: 0, width: 400, height: 200),
            1: CGRect(x: 0, y: 200, width: 400, height: 200),
            2: CGRect(x: 0, y: 400, width: 400, height: 200),
        ]
        let current: [Int: CGRect] = [
            0: CGRect(x: 0, y: 0, width: 400, height: 280),
            1: CGRect(x: 0, y: 280, width: 400, height: 200),
            2: CGRect(x: 0, y: 480, width: 400, height: 260),
        ]
        XCTAssertEqual(
            ReadingProgress.heightGrowthAboveVisibleTop(
                previous: previous,
                current: current,
                visibleTop: 390
            ),
            80
        )
    }

    func testCachedProgressDecodesContentMode() throws {
        let data = Data(#"{"index":3,"segmentCount":8,"offsetY":24,"contentMode":"original"}"#.utf8)
        let decoded = try JSONDecoder().decode(ReaderPreferences.CachedProgress.self, from: data)
        XCTAssertEqual(decoded.index, 3)
        XCTAssertEqual(decoded.offsetY, 24)
        XCTAssertEqual(decoded.contentMode, "original")
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
