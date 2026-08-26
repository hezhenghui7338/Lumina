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
}
