import XCTest
@testable import Lumina

final class LibraryImportPolicyTests: XCTestCase {
    func testSupportedExtensions_includeEpubAndMarkdownAliases() {
        XCTAssertTrue(LibraryImportPolicy.isSupported(pathExtension: "epub"))
        XCTAssertTrue(LibraryImportPolicy.isSupported(pathExtension: "EPUB"))
        XCTAssertTrue(LibraryImportPolicy.isSupported(pathExtension: "md"))
        XCTAssertTrue(LibraryImportPolicy.isSupported(pathExtension: "markdown"))
        XCTAssertTrue(LibraryImportPolicy.isSupported(pathExtension: "pdf"))
        XCTAssertTrue(LibraryImportPolicy.isSupported(pathExtension: "azw3"))
        XCTAssertTrue(LibraryImportPolicy.isSupported(pathExtension: "fb2"))
    }

    func testUnsupportedExtension_isRejected() {
        XCTAssertFalse(LibraryImportPolicy.isSupported(pathExtension: "docx.bak"))
        XCTAssertFalse(LibraryImportPolicy.isSupported(pathExtension: "png"))
        XCTAssertFalse(LibraryImportPolicy.isSupported(pathExtension: "chm"))
        XCTAssertFalse(LibraryImportPolicy.isSupported(pathExtension: ""))
    }

    func testClassify_splitsSupportedAndUnsupported() {
        let classified = LibraryImportPolicy.classify(paths: [
            "/tmp/book.epub",
            "/tmp/photo.png",
            "/tmp/notes.markdown",
            "/tmp/archive.djvu",
        ])
        XCTAssertEqual(classified.supportedPaths, ["/tmp/book.epub", "/tmp/notes.markdown"])
        XCTAssertEqual(classified.unsupportedNames, ["photo.png", "archive.djvu"])
    }

    func testClassify_emptyPaths_isEmpty() {
        let classified = LibraryImportPolicy.classify(paths: [])
        XCTAssertTrue(classified.isEmpty)
        XCTAssertTrue(classified.supportedPaths.isEmpty)
        XCTAssertTrue(classified.unsupportedNames.isEmpty)
    }

    func testUnsupportedMessage_listsNames() {
        XCTAssertEqual(
            LibraryImportPolicy.unsupportedMessage(names: ["a.png"]),
            "格式不支持：a.png"
        )
        let multi = LibraryImportPolicy.unsupportedMessage(names: ["a.png", "b.chm"])
        XCTAssertTrue(multi.hasPrefix("格式不支持："))
        XCTAssertTrue(multi.contains("a.png"))
        XCTAssertTrue(multi.contains("b.chm"))
    }

    func testPathsToForward_keepsAbsolutePathsIncludingUnsupported() {
        let urls = [
            URL(fileURLWithPath: "/Users/me/book.epub"),
            URL(fileURLWithPath: "/Users/me/skip.png"),
        ]
        XCTAssertEqual(
            LibraryImportPolicy.pathsToForward(from: urls),
            ["/Users/me/book.epub", "/Users/me/skip.png"]
        )
    }
}
