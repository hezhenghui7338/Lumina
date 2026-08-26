import XCTest
@testable import Lumina

final class BookCardCoverTests: XCTestCase {
    func testGridCover_usesFullTitleNotInitial() throws {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let card = try String(
            contentsOf: macosRoot.appendingPathComponent(
                "Lumina/Features/Library/BookCard.swift"
            ),
            encoding: .utf8
        )
        let client = try String(
            contentsOf: macosRoot.appendingPathComponent(
                "Lumina/Services/CoreClient.swift"
            ),
            encoding: .utf8
        )

        let cover = coverBlock(card)
        XCTAssertTrue(
            cover.contains("Text(book.title)"),
            "typographic cover must show the full title"
        )
        XCTAssertTrue(cover.contains(".lineLimit(5)"))
        XCTAssertTrue(cover.contains(".minimumScaleFactor(0.75)"))
        XCTAssertTrue(
            cover.contains("book.author"),
            "cover must place author when metadata is present"
        )
        XCTAssertTrue(
            cover.contains(".accessibilityHidden(true)"),
            "cover type must not be read twice by VoiceOver"
        )
        XCTAssertFalse(cover.contains("coverInitial"))
        XCTAssertFalse(cover.contains("book.title.first"))
        XCTAssertFalse(client.contains("coverInitial"))

        let windowsRoot = macosRoot
            .deletingLastPathComponent()
            .appendingPathComponent("windows/Lumina")
        let libraryXaml = try String(
            contentsOf: windowsRoot.appendingPathComponent(
                "Features/Library/LibraryPage.xaml"
            ),
            encoding: .utf8
        )
        let models = try String(
            contentsOf: windowsRoot.appendingPathComponent("Services/Models.cs"),
            encoding: .utf8
        )
        XCTAssertTrue(libraryXaml.contains("Text=\"{x:Bind Title}\""))
        XCTAssertTrue(libraryXaml.contains("BookCoverLayout.BrushFor(Category)"))
        XCTAssertTrue(libraryXaml.contains("BookCoverLayout.AuthorVisibility(Author)"))
        XCTAssertFalse(libraryXaml.contains("CoverInitial"))
        XCTAssertFalse(models.contains("CoverInitial"))
        XCTAssertTrue(models.contains("class BookCoverPalette"))
    }

    private func coverBlock(_ source: String) -> String {
        let after = source.components(separatedBy: "private var cover: some View").last ?? ""
        return after.components(separatedBy: "private var processingBar").first ?? ""
    }
}
