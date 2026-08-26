import SwiftUI

/// Reading-surface paper only. Does not change the app appearance (settings 浅色/深色).
enum ReaderPaper: String, CaseIterable, Identifiable {
    case white
    case ivory
    case sage
    case night

    var id: String { rawValue }

    var label: String {
        switch self {
        case .white: return "白"
        case .ivory: return "象牙"
        case .sage: return "护眼"
        case .night: return "夜间"
        }
    }

    /// Night paper uses light glyphs on a dark page; the other three stay dark-on-light.
    var usesLightText: Bool { self == .night }

    var page: Color {
        switch self {
        case .white: return LuminaTheme.background
        case .ivory: return Color(red: 0.98, green: 0.95, blue: 0.88)
        case .sage: return Color(red: 0.93, green: 0.95, blue: 0.90)
        case .night: return Color(red: 0.10, green: 0.10, blue: 0.12)
        }
    }

    var card: Color {
        switch self {
        case .white: return LuminaTheme.accentMuted
        case .ivory: return Color(red: 0.94, green: 0.89, blue: 0.78)
        case .sage: return Color(red: 0.86, green: 0.90, blue: 0.82)
        case .night: return Color(red: 0.16, green: 0.16, blue: 0.18)
        }
    }

    var textPrimary: Color {
        switch self {
        case .white: return LuminaTheme.textPrimary
        case .ivory: return Color(red: 0.22, green: 0.16, blue: 0.10)
        case .sage: return Color(red: 0.16, green: 0.22, blue: 0.18)
        case .night: return Color(red: 0.95, green: 0.95, blue: 0.97)
        }
    }

    var textSecondary: Color {
        switch self {
        case .white: return LuminaTheme.textSecondary
        case .ivory: return Color(red: 0.42, green: 0.35, blue: 0.28)
        case .sage: return Color(red: 0.38, green: 0.45, blue: 0.40)
        case .night: return Color(red: 0.65, green: 0.65, blue: 0.70)
        }
    }

    var border: Color {
        switch self {
        case .white: return LuminaTheme.border
        case .ivory: return Color(red: 0.88, green: 0.82, blue: 0.70)
        case .sage: return Color(red: 0.78, green: 0.84, blue: 0.76)
        case .night: return Color(red: 0.28, green: 0.28, blue: 0.32)
        }
    }
}

private struct ReaderPaperKey: EnvironmentKey {
    static let defaultValue: ReaderPaper = .white
}

extension EnvironmentValues {
    var readerPaper: ReaderPaper {
        get { self[ReaderPaperKey.self] }
        set { self[ReaderPaperKey.self] = newValue }
    }
}

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
    @AppStorage("lumina.reader.paper") var readerPaperRaw: String = ReaderPaper.white.rawValue

    /// Five reading size steps for news / book reader body text.
    static let readingFontScaleSteps: [Double] = [0.85, 1.0, 1.15, 1.3, 1.45]
    static let readingFontScaleLabels = ["较小", "标准", "较大", "大", "很大"]

    var appearance: AppearanceMode {
        get { AppearanceMode(rawValue: appearanceRaw) ?? .light }
        set { appearanceRaw = newValue.rawValue }
    }

    var colorScheme: ColorScheme? { appearance.colorScheme }

    var readerPaper: ReaderPaper {
        get { ReaderPaper(rawValue: readerPaperRaw) ?? .white }
        set {
            guard newValue.rawValue != readerPaperRaw else { return }
            objectWillChange.send()
            readerPaperRaw = newValue.rawValue
        }
    }

    var readingFontScaleLabel: String {
        guard let index = nearestScaleIndex,
              Self.readingFontScaleLabels.indices.contains(index) else {
            return "标准"
        }
        return Self.readingFontScaleLabels[index]
    }

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

/// Compact popover: A− / A+ plus four paper swatches. Not a ReaderOverlay.
struct ReaderAppearancePanel: View {
    @ObservedObject var theme: ThemeManager

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 12) {
                Button {
                    theme.decreaseReadingFont()
                } label: {
                    Text("A−")
                        .font(.system(size: 13, weight: .medium))
                        .frame(minWidth: 28)
                }
                .buttonStyle(.plain)
                .disabled(!theme.canDecreaseReadingFont)
                .help("减小字号")
                .accessibilityIdentifier("lumina.reader.control.fontDecrease")

                Spacer(minLength: 0)
                Text(theme.readingFontScaleLabel)
                    .font(.system(size: 14))
                    .foregroundStyle(LuminaTheme.textPrimary)
                    .frame(minWidth: 36)
                Spacer(minLength: 0)

                Button {
                    theme.increaseReadingFont()
                } label: {
                    Text("A+")
                        .font(.system(size: 15, weight: .semibold))
                        .frame(minWidth: 28)
                }
                .buttonStyle(.plain)
                .disabled(!theme.canIncreaseReadingFont)
                .help("增大字号")
                .accessibilityIdentifier("lumina.reader.control.fontIncrease")
            }

            HStack(spacing: 10) {
                ForEach(ReaderPaper.allCases) { paper in
                    Button {
                        theme.readerPaper = paper
                    } label: {
                        VStack(spacing: 6) {
                            Circle()
                                .fill(paper.page)
                                .frame(width: 28, height: 28)
                                .overlay {
                                    Circle()
                                        .stroke(
                                            theme.readerPaper == paper
                                                ? LuminaTheme.accent
                                                : paper.border,
                                            lineWidth: theme.readerPaper == paper ? 2 : 1
                                        )
                                }
                            Text(paper.label)
                                .font(.system(size: 11))
                                .foregroundStyle(
                                    theme.readerPaper == paper
                                        ? LuminaTheme.accent
                                        : LuminaTheme.textSecondary
                                )
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.plain)
                    .help(paper.label)
                    .accessibilityIdentifier("lumina.reader.control.paper.\(paper.rawValue)")
                    .accessibilityAddTraits(
                        theme.readerPaper == paper ? .isSelected : []
                    )
                }
            }
        }
        .padding(14)
        .frame(width: 248)
        .absorbsReaderChromeClicks()
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
