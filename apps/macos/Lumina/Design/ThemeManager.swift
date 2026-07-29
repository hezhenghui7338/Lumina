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
    @AppStorage("lumina.readingFontScale") var readingFontScale: Double = 1.0

    /// Five reading size steps for news / skim surfaces.
    static let readingFontScaleSteps: [Double] = [0.85, 1.0, 1.15, 1.3, 1.45]

    var appearance: AppearanceMode {
        get { AppearanceMode(rawValue: appearanceRaw) ?? .light }
        set { appearanceRaw = newValue.rawValue }
    }

    var colorScheme: ColorScheme? { appearance.colorScheme }

    func scaled(_ base: CGFloat) -> CGFloat {
        base * CGFloat(readingFontScale)
    }

    var canDecreaseReadingFont: Bool {
        readingFontScale > Self.readingFontScaleSteps.first! + 0.001
    }

    var canIncreaseReadingFont: Bool {
        readingFontScale < Self.readingFontScaleSteps.last! - 0.001
    }

    func decreaseReadingFont() {
        guard let current = nearestScaleIndex, current > 0 else { return }
        objectWillChange.send()
        readingFontScale = Self.readingFontScaleSteps[current - 1]
    }

    func increaseReadingFont() {
        guard let current = nearestScaleIndex, current < Self.readingFontScaleSteps.count - 1 else { return }
        objectWillChange.send()
        readingFontScale = Self.readingFontScaleSteps[current + 1]
    }

    private var nearestScaleIndex: Int? {
        let steps = Self.readingFontScaleSteps
        guard !steps.isEmpty else { return nil }
        var best = 0
        var bestDist = abs(steps[0] - readingFontScale)
        for i in 1..<steps.count {
            let d = abs(steps[i] - readingFontScale)
            if d < bestDist {
                bestDist = d
                best = i
            }
        }
        return best
    }
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
