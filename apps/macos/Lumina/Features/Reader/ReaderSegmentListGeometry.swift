import CoreGraphics

enum ReaderSegmentListGeometry {
    static func isPointerInSegmentList(_ point: CGPoint, segmentsWidth: CGFloat) -> Bool {
        point.x <= segmentsWidth
    }
}

/// Maps the visible reading position to persisted progress.
///
/// Progress is the segment pinned to the top of the viewport. A trailing spacer
/// lets the last segment reach that anchor; peeking the last segment at the
/// bottom of the screen must not mark the book finished.
enum ReadingProgress {
    static func saveIndex(visibleIndex: Int, lastIndex: Int?) -> Int {
        guard let lastIndex else { return max(visibleIndex, 0) }
        return min(max(visibleIndex, 0), lastIndex)
    }

    /// Prefer the locally cached index after a crash/quit if the book was not
    /// resegmented. Ignore cache when segment count changed.
    static func restoreIndex(
        serverIndex: Int,
        localIndex: Int?,
        localSegmentCount: Int?,
        currentSegmentCount: Int
    ) -> Int {
        let last = max(currentSegmentCount - 1, 0)
        if let localIndex,
           localSegmentCount == currentSegmentCount,
           currentSegmentCount > 0 {
            return min(max(localIndex, 0), last)
        }
        return min(max(serverIndex, 0), last)
    }

    /// Extra scrollable space so the last segment can pin to `.top`.
    static func endPinSpacerHeight(viewportHeight: CGFloat) -> CGFloat {
        max(viewportHeight - 64, 120)
    }

    static let feedCoordinateSpace = "lumina.reader.feed"

    struct ViewportAnchor: Equatable {
        var index: Int
        var offsetY: CGFloat
    }

    /// Map the feed Y at the viewport top to a segment. This is the runtime
    /// source of truth for progress — not SwiftUI `scrollPosition`.
    ///
    /// Only a frame that actually contains `visibleTop` counts. Incomplete
    /// LazyVStack frames must not snap to the first/last reported segment
    /// (that writes progress back to 0 / "home").
    static func viewportAnchor(visibleTop: CGFloat, frames: [Int: CGRect]) -> ViewportAnchor? {
        guard !frames.isEmpty else { return nil }
        let sorted = frames.sorted { $0.value.minY < $1.value.minY }
        let slop: CGFloat = 1
        if let hit = sorted.first(where: {
            $0.value.minY - slop <= visibleTop && visibleTop < $0.value.maxY + slop
        }) {
            return ViewportAnchor(index: hit.key, offsetY: max(0, visibleTop - hit.value.minY))
        }
        return nil
    }

    /// Reject a jump to segment 0 unless the viewport really contains it.
    static func shouldCommitProgress(
        previousIndex: Int?,
        nextIndex: Int,
        hitContained: Bool
    ) -> Bool {
        if nextIndex == 0, let previousIndex, previousIndex > 0, !hitContained {
            return false
        }
        return true
    }

    /// Last-line cache guard: do not let an unconfirmed index 0 overwrite a
    /// mid-book cache with the same segment count.
    static func shouldReplaceCachedIndex(
        cachedIndex: Int?,
        cachedSegmentCount: Int?,
        nextIndex: Int,
        nextSegmentCount: Int,
        confirmedHit: Bool
    ) -> Bool {
        if let cachedSegmentCount, cachedSegmentCount != nextSegmentCount {
            return true
        }
        return shouldCommitProgress(
            previousIndex: cachedIndex,
            nextIndex: nextIndex,
            hitContained: confirmedHit
        )
    }

    /// Skip an origin restore attempt when the document is still too short
    /// (LazyVStack rematerializing from the start). Clamping to 0 would stick
    /// the reader on the first page.
    static func shouldApplyRestoredOrigin(targetY: CGFloat, maxY: CGFloat, slop: CGFloat = 8) -> Bool {
        targetY <= maxY + slop
    }

    static func restoreOffsetY(
        localOffsetY: Double?,
        localSegmentCount: Int?,
        currentSegmentCount: Int,
        localContentMode: String? = nil,
        currentContentMode: String? = nil
    ) -> CGFloat {
        guard localSegmentCount == currentSegmentCount, currentSegmentCount > 0 else {
            return 0
        }
        if let localContentMode, let currentContentMode, localContentMode != currentContentMode {
            return 0
        }
        return CGFloat(max(0, localOffsetY ?? 0))
    }

    /// Feed-space Y of the restored viewport top, or nil until the target frame exists.
    static func restoredOriginY(
        index: Int,
        offsetY: CGFloat,
        frames: [Int: CGRect]
    ) -> CGFloat? {
        guard let frame = frames[index] else { return nil }
        return frame.minY + max(0, offsetY)
    }

    static func canApplyRestore(
        index: Int,
        offsetY: CGFloat,
        frames: [Int: CGRect],
        maxY: CGFloat
    ) -> Bool {
        guard let y = restoredOriginY(index: index, offsetY: offsetY, frames: frames) else {
            return false
        }
        return shouldApplyRestoredOrigin(targetY: y, maxY: maxY)
    }

    /// Height growth of segments fully above the viewport. Used to compensate
    /// origin once when a skeleton hydrates, without nilling `scrollPosition`.
    static func heightGrowthAboveVisibleTop(
        previous: [Int: CGRect],
        current: [Int: CGRect],
        visibleTop: CGFloat
    ) -> CGFloat {
        var delta: CGFloat = 0
        for (idx, oldFrame) in previous {
            guard oldFrame.maxY <= visibleTop + 1 else { continue }
            guard let newFrame = current[idx] else { continue }
            delta += newFrame.height - oldFrame.height
        }
        return delta
    }
}

/// Exclusive intents for the reader feed. Tracking is the only phase that
/// persists progress from the viewport; jump is the only command that writes
/// SwiftUI `scrollPosition` after the initial restore pin.
enum ReaderScrollPhase: Equatable {
    case tracking
    case restoring
    case jumping
    case preserving

    var allowsProgressSave: Bool { self == .tracking }
    var allowsViewportDrivenSelection: Bool { self == .tracking }
    var cancelsOriginRestore: Bool { self == .jumping }
}

enum ReaderRestoreStep: Equatable {
    case waiting
    case apply(CGFloat)
    case finished
}

/// Event-driven restore: wait for the target frame, apply origin once, then stop.
struct ReaderRestoreAttempt: Equatable {
    let index: Int
    let offsetY: CGFloat
    private(set) var applied = false
    private(set) var retryUsed = false

    init(index: Int, offsetY: CGFloat) {
        self.index = index
        self.offsetY = offsetY
    }

    var needsOriginAdjust: Bool { offsetY > 1 }

    mutating func step(frames: [Int: CGRect], maxY: CGFloat) -> ReaderRestoreStep {
        if applied { return .finished }
        if !needsOriginAdjust {
            applied = true
            return .finished
        }
        guard let y = ReadingProgress.restoredOriginY(
            index: index,
            offsetY: offsetY,
            frames: frames
        ) else {
            return .waiting
        }
        if ReadingProgress.shouldApplyRestoredOrigin(targetY: y, maxY: maxY) {
            return .apply(y)
        }
        if retryUsed {
            applied = true
            return .finished
        }
        retryUsed = true
        return .waiting
    }

    mutating func markApplied() {
        applied = true
    }
}

enum ReaderKeyboardScroll {
    static let lineDelta: CGFloat = 80
    static let pageFactor: CGFloat = 0.9
    static let minPageHeight: CGFloat = 120
    private static let edgeEpsilon: CGFloat = 0.5

    static func pageDelta(viewportHeight: CGFloat, page: Int) -> CGFloat {
        CGFloat(page) * max(viewportHeight * pageFactor, minPageHeight)
    }

    static func clampedOriginY(
        currentY: CGFloat,
        deltaY: CGFloat,
        viewportHeight: CGFloat,
        contentHeight: CGFloat
    ) -> CGFloat {
        let maxY = max(0, contentHeight - viewportHeight)
        return min(max(0, currentY + deltaY), maxY)
    }

    static func canMove(originY: CGFloat, deltaY: CGFloat, maxY: CGFloat) -> Bool {
        if deltaY > 0 { return originY < maxY - edgeEpsilon }
        if deltaY < 0 { return originY > edgeEpsilon }
        return false
    }
}

enum ReaderSegmentPanelHeight {
    static let minHeight: CGFloat = 160
    static let maxHeight: CGFloat = 420

    static func clamp(_ height: CGFloat) -> CGFloat {
        min(max(height, minHeight), maxHeight)
    }

    /// Boxed source viewport: prefer the larger of locked and capped measured height
    /// so a stale low lock does not shrink the panel below the last summary measurement.
    static func boxedViewportHeight(measured: CGFloat, locked: CGFloat?) -> CGFloat {
        let cappedMeasured = clamp(measured)
        guard let locked else { return cappedMeasured }
        return max(locked, cappedMeasured)
    }

    static let measurementEpsilon: CGFloat = 1

    /// Ignore sub-point height jitter from NSTextView layout so @State does not loop.
    static func shouldCommitMeasurement(current: CGFloat, incoming: CGFloat) -> Bool {
        incoming > 0 && abs(incoming - current) >= measurementEpsilon
    }
}
