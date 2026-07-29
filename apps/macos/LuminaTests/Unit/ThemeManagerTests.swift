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
    }
}
