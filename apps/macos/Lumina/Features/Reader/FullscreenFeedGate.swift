import Foundation

/// During system fullscreen enter/exit, the full-segment LazyVStack re-evaluates
/// thousands of rows (seg_block≈6k on a 9998-segment book) and freezes MainActor.
/// Gate the feed to a thin slice around the pinned segment for the transition only;
/// steady-state still uses the full `ForEach(segments)` (d383158 product lock).
enum FullscreenFeedGate {
    /// Rows on each side of the pin while gated (~25 total).
    static let radius: Int = 12

    /// Match width-settle debounce so restore waits until geometry stops churning.
    static var settleNanoseconds: UInt64 {
        LuminaTextLayoutSizing.widthSettleNanoseconds
    }

    enum Event: String {
        case willEnter
        case didEnter
        case willExit
        case didExit

        /// `true` = engage gate now; `false` = schedule release after settle.
        var engagesGate: Bool {
            switch self {
            case .willEnter, .willExit: return true
            case .didEnter, .didExit: return false
            }
        }
    }

    /// Contiguous slice of `segments` around `pinIndex` (by array position of matching idx).
    static func slice(
        segments: [SegmentRow],
        pinIndex: Int?,
        radius: Int = radius
    ) -> [SegmentRow] {
        guard !segments.isEmpty else { return [] }
        let pin = pinIndex ?? segments[0].idx
        let pos: Int
        if let exact = segments.firstIndex(where: { $0.idx == pin }) {
            pos = exact
        } else {
            pos = segments.indices.min(by: {
                abs(segments[$0].idx - pin) < abs(segments[$1].idx - pin)
            }) ?? 0
        }
        let start = max(0, pos - radius)
        let end = min(segments.count - 1, pos + radius)
        return Array(segments[start...end])
    }

    /// True while the feed must not run visible prefetch / viewport spacer commits.
    static func shouldSuppressFeedChurn(gated: Bool) -> Bool { gated }
}

extension Notification.Name {
    /// Posted on system fullscreen will/did enter/exit. userInfo["kind"] = Event.rawValue.
    static let luminaFullscreenTransition = Notification.Name("luminaFullscreenTransition")
}
