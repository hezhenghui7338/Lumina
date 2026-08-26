import XCTest
@testable import Lumina

final class MarkdownExportModeTests: XCTestCase {
    func testSentencesModeOmitsNotesAndUsesBriefFilename() {
        XCTAssertEqual(MarkdownExportMode.full.apiValue, "full")
        XCTAssertEqual(MarkdownExportMode.sentences.apiValue, "sentences")
        XCTAssertTrue(MarkdownExportMode.full.allowsNotes)
        XCTAssertFalse(MarkdownExportMode.sentences.allowsNotes)
        XCTAssertEqual(
            BookMarkdownExporter.defaultFilename(for: "三体", mode: .full),
            "三体-summary.md"
        )
        XCTAssertEqual(
            BookMarkdownExporter.defaultFilename(for: "三体", mode: .sentences),
            "三体-总结.md"
        )
    }
}
