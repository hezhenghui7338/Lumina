import SwiftUI

enum LuminaTheme {
    static let background = Color(red: 0.98, green: 0.98, blue: 0.99)
    static let surface = Color.white
    static let accent = Color(red: 0.95, green: 0.45, blue: 0.15)
    static let accentMuted = Color(red: 0.98, green: 0.92, blue: 0.86)
    static let textPrimary = Color(red: 0.12, green: 0.12, blue: 0.14)
    static let textSecondary = Color(red: 0.45, green: 0.45, blue: 0.50)
    static let border = Color(red: 0.90, green: 0.90, blue: 0.92)
    static let sidebarWidth: CGFloat = 260

    // MARK: - Summary reading typography

    /// Lead summary sentences (~18–20pt).
    static let summaryLeadSize: CGFloat = 19
    static let summaryLeadLineSpacing: CGFloat = 7
    static let summaryLeadParagraphSpacing: CGFloat = 14
    /// Structured bullet body.
    static let summaryBulletSize: CGFloat = 15
    static let summaryBulletLineSpacing: CGFloat = 4
    static let summaryBulletItemSpacing: CGFloat = 12
    /// Section label / anchor.
    static let summaryLabelSize: CGFloat = 12
    static let summarySectionSpacing: CGFloat = 20
    /// Side/inset padding only — body fills available width (WeChat Reading–style).
    static let summaryPadding: CGFloat = 20
    static let summaryCornerRadius: CGFloat = 12

    /// Segment content panel viewport (summary / source toggle box).
    static let segmentContentMinHeight: CGFloat = 160
    static let segmentContentMaxHeight: CGFloat = 420
}

struct LuminaCardStyle: ViewModifier {
    func body(content: Content) -> some View {
        content
            .padding(12)
            .background(LuminaTheme.surface)
            .clipShape(RoundedRectangle(cornerRadius: 10))
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(LuminaTheme.border, lineWidth: 1))
    }
}

/// Reading body fills the available width; callers supply padding separately.
struct ReadingColumnModifier: ViewModifier {
    func body(content: Content) -> some View {
        content
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

extension View {
    func luminaCard() -> some View { modifier(LuminaCardStyle()) }

    func readingColumn() -> some View {
        modifier(ReadingColumnModifier())
    }
}
