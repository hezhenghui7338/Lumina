import SwiftUI

enum AppearanceMode: String, CaseIterable, Identifiable {
    case system
    case light
    case dark

    var id: String { rawValue }

    var label: String {
        switch self {
        case .system: return "跟随系统"
        case .light: return "浅色"
        case .dark: return "深色"
        }
    }

    var colorScheme: ColorScheme? {
        switch self {
        case .system: return nil
        case .light: return .light
        case .dark: return .dark
        }
    }
}

@MainActor
final class ThemeManager: ObservableObject {
    @AppStorage("lumina.appearance") var appearanceRaw: String = AppearanceMode.light.rawValue

    var appearance: AppearanceMode {
        get { AppearanceMode(rawValue: appearanceRaw) ?? .light }
        set { appearanceRaw = newValue.rawValue }
    }

    var colorScheme: ColorScheme? { appearance.colorScheme }
}

extension LuminaTheme {
    static func background(for scheme: ColorScheme) -> Color {
        scheme == .dark ? Color(red: 0.10, green: 0.10, blue: 0.12) : background
    }

    static func surface(for scheme: ColorScheme) -> Color {
        scheme == .dark ? Color(red: 0.16, green: 0.16, blue: 0.18) : surface
    }

    static func textPrimary(for scheme: ColorScheme) -> Color {
        scheme == .dark ? Color(red: 0.95, green: 0.95, blue: 0.97) : textPrimary
    }

    static func textSecondary(for scheme: ColorScheme) -> Color {
        scheme == .dark ? Color(red: 0.65, green: 0.65, blue: 0.70) : textSecondary
    }

    static func border(for scheme: ColorScheme) -> Color {
        scheme == .dark ? Color(red: 0.28, green: 0.28, blue: 0.32) : border
    }
}
