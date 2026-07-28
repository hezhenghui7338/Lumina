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

extension View {
    func luminaCard() -> some View { modifier(LuminaCardStyle()) }
}
