import SwiftUI

/// What a click on reader reading content means for the chrome.
///
/// Who receives the click is decided by SwiftUI hit-testing, not by inspecting
/// AppKit views: a SwiftUI Button, a text label and blank space all hit-test to
/// the same `PlatformGroupContainer`, so an AppKit/AX guess cannot tell them
/// apart. Controls therefore keep their own clicks, and only clicks that reach
/// the reading surface arrive here.
enum ReaderChromeClickOutcome: Equatable {
    /// An overlay owns the click (its dimmed backdrop closes it instead).
    case ignore
    /// Retract the hover-peeked segment list before touching the chrome.
    case closeSegmentPeek
    case collapse
    case reveal
}

enum ReaderChromeClickPolicy {
    static func outcome(
        overlayOpen: Bool,
        segmentPeekVisible: Bool,
        chromeHidden: Bool
    ) -> ReaderChromeClickOutcome {
        if overlayOpen { return .ignore }
        if segmentPeekVisible { return .closeSegmentPeek }
        return chromeHidden ? .reveal : .collapse
    }
}

extension View {
    /// Makes a reader control strip own every click inside it. A disabled
    /// SwiftUI Button is not hit-testable, so without this a click on a greyed
    /// out control (or on the gap between controls) falls through and toggles
    /// the chrome.
    func absorbsReaderChromeClicks() -> some View {
        contentShape(Rectangle())
            .onTapGesture {}
    }
}
