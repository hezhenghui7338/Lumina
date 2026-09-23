import XCTest
@testable import Lumina

@MainActor
final class ThemeManagerTests: XCTestCase {
    func testDecreaseReadingFont_atMin_disabled() {
        let theme = ThemeManager()
        theme.readingFontScale = ThemeManager.readingFontScaleSteps.first!
        XCTAssertFalse(theme.canDecreaseReadingFont)
    }

    func testIncreaseReadingFont_atMax_disabled() {
        let theme = ThemeManager()
        theme.readingFontScale = ThemeManager.readingFontScaleSteps.last!
        XCTAssertFalse(theme.canIncreaseReadingFont)
    }

    func testFontScaleSteps() {
        let theme = ThemeManager()
        theme.readingFontScale = 1.0
        XCTAssertTrue(theme.canDecreaseReadingFont)
        XCTAssertTrue(theme.canIncreaseReadingFont)

        theme.increaseReadingFont()
        XCTAssertEqual(theme.readingFontScale, 1.15, accuracy: 0.001)

        theme.decreaseReadingFont()
        XCTAssertEqual(theme.readingFontScale, 1.0, accuracy: 0.001)
        XCTAssertEqual(theme.readingFontScaleLabel, "标准")
    }

    func testLineSpacingDefaultIsSlightlyLoose() {
        XCTAssertEqual(
            ThemeManager.defaultReadingLineSpacingScale,
            1.2,
            accuracy: 0.001
        )
        XCTAssertEqual(ThemeManager.readingLineSpacingScaleSteps.count, 5)
        XCTAssertEqual(
            ThemeManager.readingLineSpacingScaleSteps[2],
            ThemeManager.defaultReadingLineSpacingScale,
            accuracy: 0.001
        )
    }

    func testLineSpacingSteps() {
        let theme = ThemeManager()
        theme.readingLineSpacingScale = ThemeManager.defaultReadingLineSpacingScale
        XCTAssertEqual(theme.readingLineSpacingScaleLabel, "标准")
        XCTAssertTrue(theme.canDecreaseReadingLineSpacing)
        XCTAssertTrue(theme.canIncreaseReadingLineSpacing)

        theme.increaseReadingLineSpacing()
        XCTAssertEqual(theme.readingLineSpacingScale, 1.4, accuracy: 0.001)
        XCTAssertEqual(theme.readingLineSpacingScaleLabel, "较疏")

        theme.decreaseReadingLineSpacing()
        XCTAssertEqual(theme.readingLineSpacingScale, 1.2, accuracy: 0.001)
        XCTAssertEqual(theme.readingLineSpacingScaleLabel, "标准")
    }

    func testLineSpacedAppliesFontAndLineMultipliers() {
        let theme = ThemeManager()
        theme.readingFontScale = 1.0
        theme.readingLineSpacingScale = 1.2
        XCTAssertEqual(
            theme.lineSpaced(10),
            12,
            accuracy: 0.001
        )
        theme.readingFontScale = 1.15
        XCTAssertEqual(
            theme.lineSpaced(10),
            10 * 1.15 * 1.2,
            accuracy: 0.001
        )
    }

    func testDecreaseReadingLineSpacing_atMin_disabled() {
        let theme = ThemeManager()
        theme.readingLineSpacingScale = ThemeManager.readingLineSpacingScaleSteps.first!
        XCTAssertFalse(theme.canDecreaseReadingLineSpacing)
    }

    func testIncreaseReadingLineSpacing_atMax_disabled() {
        let theme = ThemeManager()
        theme.readingLineSpacingScale = ThemeManager.readingLineSpacingScaleSteps.last!
        XCTAssertFalse(theme.canIncreaseReadingLineSpacing)
    }

    func testNightPaperUsesLightTextOnDarkPage() {
        XCTAssertTrue(ReaderPaper.night.usesLightText)
        XCTAssertFalse(ReaderPaper.white.usesLightText)
        XCTAssertFalse(ReaderPaper.ivory.usesLightText)
        XCTAssertFalse(ReaderPaper.sage.usesLightText)
        XCTAssertEqual(ReaderPaper.allCases.count, 4)
        XCTAssertEqual(ReaderPaper.white.page, LuminaTheme.background)
        XCTAssertEqual(ReaderPaper.white.textPrimary, LuminaTheme.textPrimary)
    }

    func testReaderPaperDoesNotChangeAppAppearance() {
        let theme = ThemeManager()
        let before = theme.appearanceRaw
        theme.readerPaper = .night
        XCTAssertEqual(theme.readerPaper, .night)
        XCTAssertEqual(theme.appearanceRaw, before)
        theme.readerPaper = .white
        XCTAssertEqual(theme.appearanceRaw, before)
    }

    func testAppearancePanelExposesLineSpacingNotLetterSpacing() throws {
        let url = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // Unit
            .deletingLastPathComponent() // LuminaTests
            .appendingPathComponent("Lumina/Design/ThemeManager.swift")
        let themeSource = try String(contentsOf: url, encoding: .utf8)
        XCTAssertTrue(themeSource.contains("title: \"行间距\""))
        XCTAssertFalse(themeSource.contains("字间距"))
        XCTAssertTrue(themeSource.contains("readingLineSpacingScale"))
        XCTAssertFalse(themeSource.contains("readingLetterSpacing"))
        XCTAssertFalse(themeSource.contains("kerning"))
    }
}
