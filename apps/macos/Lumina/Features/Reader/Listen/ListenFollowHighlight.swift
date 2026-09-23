import SwiftUI

/// Soft follow-along background for SwiftUI listen targets
/// (segment title, summary sentence, section header, bullet row).
/// Does **not** auto-scroll — that fights segment advance / hydrate (PRD §5.3.1).
struct ListenFollowHighlightModifier: ViewModifier {
    let isActive: Bool

    func body(content: Content) -> some View {
        content
            .padding(.horizontal, isActive ? 4 : 0)
            .padding(.vertical, isActive ? 2 : 0)
            .background(
                RoundedRectangle(cornerRadius: 4)
                    .fill(isActive ? LuminaTheme.listenFollowHighlight : Color.clear)
            )
            .animation(.easeOut(duration: 0.15), value: isActive)
    }
}

/// Policy for listen follow-along UI side effects.
enum ListenFollowHighlightPolicy {
    /// Must stay false: auto-scrolling spoken lines via reveal fights
    /// `onHighlightSegment` → navigate / hydrate and stalls continuous play.
    static let scrollsUtteranceIntoView = false
}

extension View {
    func listenFollowHighlight(_ isActive: Bool) -> some View {
        modifier(ListenFollowHighlightModifier(isActive: isActive))
    }
}
