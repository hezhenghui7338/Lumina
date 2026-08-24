import CoreGraphics

enum ReaderSegmentListGeometry {
    static func isPointerInSegmentList(_ point: CGPoint, segmentsWidth: CGFloat) -> Bool {
        point.x <= segmentsWidth
    }
}

/// Toolbar / edge-icon click pins the list. Left-edge hover only peeks.
struct ReaderSegmentListVisibility: Equatable {
    var pinned: Bool
    var peeking: Bool

    var overlayVisible: Bool { peeking && !pinned }
    var inlineVisible: Bool { pinned }
    var anyVisible: Bool { overlayVisible || inlineVisible }

    static let hidden = ReaderSegmentListVisibility(pinned: false, peeking: false)
}

enum ReaderSegmentListPolicy {
    /// Window toolbar and left-edge icon: persist as an inline sidebar.
    static func toggleByExplicitClick(
        _ state: ReaderSegmentListVisibility
    ) -> ReaderSegmentListVisibility {
        if state.pinned {
            return .hidden
        }
        return ReaderSegmentListVisibility(pinned: true, peeking: false)
    }

    /// Left-edge dwell: overlay peek that retracts when the pointer leaves.
    static func beginEdgePeek(
        _ state: ReaderSegmentListVisibility
    ) -> ReaderSegmentListVisibility {
        if state.pinned { return state }
        return ReaderSegmentListVisibility(pinned: false, peeking: true)
    }

    /// Pointer left the overlay, blank click, or chrome collapse. Does not unpin.
    static func endPeek(
        _ state: ReaderSegmentListVisibility
    ) -> ReaderSegmentListVisibility {
        var next = state
        next.peeking = false
        return next
    }

    /// Header pin while peeking.
    static func pin(
        _: ReaderSegmentListVisibility
    ) -> ReaderSegmentListVisibility {
        ReaderSegmentListVisibility(pinned: true, peeking: false)
    }

    /// Header chevron: dismiss peek or unpin.
    static func close(
        _: ReaderSegmentListVisibility
    ) -> ReaderSegmentListVisibility {
        .hidden
    }
}

/// Reading progress is the segment pinned to the top of the viewport, reported
/// by SwiftUI's `scrollPosition(id:anchor:.top)`.
///
/// There is deliberately no geometry here: deriving the segment from pixel
/// offsets and LazyVStack frames, while AppKit also nudged the scroll origin,
/// is what made progress unreliable. Anchoring has exactly one owner (SwiftUI)
/// and progress has exactly one source (the pinned segment).
enum ReadingProgress {
    /// Prefer the locally recorded index unless the book was resegmented since
    /// it was written, in which case the server index is the safer resume.
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

    /// Derived 0...1 for progress bars. Labels and persistence use the segment
    /// index, not this value.
    static func percent(index: Int, count: Int) -> Double {
        guard count > 1 else { return 0 }
        let last = count - 1
        let idx = min(max(index, 0), last)
        if idx >= last { return 1 }
        return min(1, max(0, Double(idx) / Double(count)))
    }

    static func isFinished(index: Int, count: Int) -> Bool {
        count > 1 && index >= count - 1
    }

    static func statusLabel(opened: Bool, index: Int, segmentCount: Int) -> String {
        guard opened else { return "未读" }
        guard segmentCount > 0 else { return "在读" }
        let last = segmentCount - 1
        let idx = min(max(index, 0), last)
        if isFinished(index: idx, count: segmentCount) { return "已读完" }
        return "在读 · \(idx + 1)/\(segmentCount) 段"
    }
}

/// The reader has two states and no more. While `restoring`, the pinned segment
/// is whatever SwiftUI has managed to scroll to so far and must not be recorded;
/// once `reading`, the pinned segment is the progress.
enum ReaderProgressPhase: Equatable {
    case restoring
    case reading

    var recordsProgress: Bool { self == .reading }
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

/// Prev/next segment by sorted idx, used by [ ] buttons and keyboard.
enum SegmentTurnNavigation {
    static func targetIdx(current: Int, delta: Int, sortedIdxs: [Int]) -> Int? {
        guard let pos = sortedIdxs.firstIndex(of: current) else { return nil }
        let newPos = pos + delta
        guard sortedIdxs.indices.contains(newPos) else { return nil }
        return sortedIdxs[newPos]
    }
}
