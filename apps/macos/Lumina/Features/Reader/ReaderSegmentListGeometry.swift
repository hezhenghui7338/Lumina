import CoreGraphics

/// Segment catalog overlay over the reader. Must not insert a column that
/// squeezes the reading surface. Recents while reading is not a surface.
enum ReaderCoverPage: Equatable {
    case none
    case segments

    var isOpen: Bool { self != .none }
    var showsSegments: Bool { self == .segments }
}

enum ReaderCoverPagePolicy {
    /// Bottom-bar catalog click. Same target again closes the page.
    static func toggle(
        _ current: ReaderCoverPage,
        to target: ReaderCoverPage
    ) -> ReaderCoverPage {
        guard target != .none else { return .none }
        return current == target ? .none : target
    }

    static func close() -> ReaderCoverPage { .none }

    /// Choosing a segment dismisses the cover so reading is visible.
    static func selectItem() -> ReaderCoverPage { .none }
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
/// once `reading`, the pinned segment is the progress — unless a seek gate is
/// holding commits after an intentional jump.
enum ReaderProgressPhase: Equatable {
    case restoring
    case reading

    var recordsProgress: Bool { self == .reading }
}

/// After search / catalog / citation / note / ⌘K jumps, do not overwrite the
/// saved reading position until the reader has moved through
/// `requiredDistinctSegments` *additional* distinct pins (the landing segment
/// itself does not count). Optionally shows a non-blocking "return to saved
/// progress" offer while seeking.
///
/// Jump animations / LazyVStack materialization can briefly pin intermediate
/// segments before the landing. Those must not count toward the three-pin
/// gate or the offer disappears before the user sees it.
struct ReadingProgressCommitGate: Equatable {
    static let requiredDistinctSegments = 3

    private(set) var isSeeking = false
    /// When true, the reader should show the return-progress banner.
    private(set) var offerVisible = false
    /// Saved index at the moment of the jump; used by the return offer.
    private(set) var savedIndex: Int?
    private var landing: Int?
    /// False until the jump target has been pinned at least once.
    private var landingConfirmed = false
    private var distinctAfterLanding: [Int] = []

    mutating func reset() {
        isSeeking = false
        offerVisible = false
        savedIndex = nil
        landing = nil
        landingConfirmed = false
        distinctAfterLanding = []
    }

    /// Enter seek mode at an intentional jump target. When landing equals the
    /// already-saved progress, clears any prior seek (no offer) and stays armed.
    /// Re-entering elsewhere resets the distinct-segment counter and re-shows
    /// the offer.
    @discardableResult
    mutating func beginSeek(at landing: Int, savedIndex: Int) -> Bool {
        if landing == savedIndex {
            reset()
            return false
        }
        isSeeking = true
        offerVisible = true
        self.savedIndex = savedIndex
        self.landing = landing
        landingConfirmed = false
        distinctAfterLanding = []
        return true
    }

    /// User chose "stay here": clear seek/offer so the caller can commit the
    /// current pin immediately and resume normal recording.
    mutating func adoptHere() {
        reset()
    }

    /// User accepted "return to last progress". Returns the index to jump to
    /// and clears seek state.
    mutating func acceptReturn() -> Int? {
        guard isSeeking, let saved = savedIndex else { return nil }
        let target = saved
        reset()
        return target
    }

    /// Whether this pin should be written as reading progress. Committing
    /// clears seek state and the offer.
    mutating func shouldCommit(pinned idx: Int) -> Bool {
        guard isSeeking else { return true }
        if !landingConfirmed {
            if idx == landing {
                landingConfirmed = true
            }
            // Ignore pre-landing flash pins from the jump scroll.
            return false
        }
        if idx == landing {
            // Still on (or back on) the jump landing — not "reading through".
            return false
        }
        if !distinctAfterLanding.contains(idx) {
            distinctAfterLanding.append(idx)
        }
        if distinctAfterLanding.count >= Self.requiredDistinctSegments {
            reset()
            return true
        }
        return false
    }
}

/// Payload for the non-blocking return-progress banner.
struct ProgressReturnOffer: Equatable {
    let savedIndex: Int
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

/// Height reserved for a segment that does not yet have a summary, so
/// `pending` → `running` → `ready` does not explode the feed and yank
/// `scrollPosition` back to the pinned segment's top.
enum SegmentSummaryPlaceholderHeight {
    static let minimum: CGFloat = 200
    static let maximum: CGFloat = 600
    static let charsPerPoint: CGFloat = 6

    static func reserved(charCount: Int?) -> CGFloat {
        guard let charCount, charCount > 0 else { return minimum }
        return min(max(CGFloat(charCount) / charsPerPoint, minimum), maximum)
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

/// Hardware `[` / `]` (keyCode 33 / 30). Chinese IME types 【】 on the same keys.
/// Character `onKeyPress` only fires while the SwiftUI reader view is first
/// responder; after a turn, selectable body text steals focus and the second
/// press dies. Key codes keep working.
enum SegmentTurnKeyPolicy {
    static let openBracketKeyCode: UInt16 = 33
    static let closeBracketKeyCode: UInt16 = 30

    static func delta(
        keyCode: UInt16,
        characters: String,
        shift: Bool,
        isRepeat: Bool
    ) -> Int? {
        if isRepeat { return nil }
        if shift { return nil }
        switch keyCode {
        case openBracketKeyCode: return -1
        case closeBracketKeyCode: return 1
        default:
            break
        }
        switch characters {
        case "[", "【": return -1
        case "]", "】": return 1
        default: return nil
        }
    }
}
