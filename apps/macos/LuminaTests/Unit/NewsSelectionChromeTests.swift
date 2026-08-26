import SwiftUI
import XCTest
@testable import Lumina

final class NewsSelectionChromeTests: XCTestCase {
    func testNewsRowSelectionBackground_matchesAccentMuted() {
        XCTAssertEqual(
            LuminaTheme.newsRowSelectionBackground,
            LuminaTheme.accentMuted,
            "selected news rows must stay on the light accent tint so textPrimary stays readable"
        )
    }

    func testNewsRowSelectionStroke_isLowOpacityAccent() throws {
        let source = try macosSource("Lumina/Design/DesignSystem.swift")
        XCTAssertTrue(
            source.contains("static let newsRowSelectionStroke = accent.opacity(0.25)"),
            "news selection stroke must be accent at 0.25 opacity, not a solid fill"
        )
        XCTAssertFalse(
            source.contains("static let newsRowSelectionBackground = accent\n"),
            "news selection fill must not use full accent"
        )
    }

    func testNewsSidebar_usesCustomChromeInsteadOfSystemListSelection() throws {
        let source = try macosSource("Lumina/Features/News/NewsView.swift")
        XCTAssertFalse(
            source.contains("List(selection:"),
            "system List selection paints a dark accent over textPrimary"
        )
        XCTAssertTrue(source.contains("newsRowSelectionBackground"))
        XCTAssertTrue(source.contains("newsRowSelectionStroke"))
        XCTAssertTrue(source.contains("newsRowSelectionChrome"))
        XCTAssertTrue(source.contains("textPrimary"))
        XCTAssertTrue(source.contains("accessibilityAddTraits"))
        XCTAssertTrue(source.contains("clickCount == 2"))
        XCTAssertTrue(source.contains("onMoveCommand"))
    }

    private func macosSource(_ relative: String) throws -> String {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        return try String(
            contentsOf: macosRoot.appendingPathComponent(relative),
            encoding: .utf8
        )
    }
}
