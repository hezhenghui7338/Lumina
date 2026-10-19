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

    func testURLParse_splitsOnSemicolonAndSkipsBlanks() {
        let parsed = WebURLImportPolicy.parse(
            " https://Example.com/a ; ;ftp://files.example/x; https://example.com/b "
        )
        XCTAssertEqual(parsed.urls, ["https://Example.com/a", "https://example.com/b"])
        XCTAssertEqual(parsed.invalid, ["ftp://files.example/x"])
    }

    func testURLParse_rejectsBareText() {
        let parsed = WebURLImportPolicy.parse("不是网址")
        XCTAssertTrue(parsed.urls.isEmpty)
        XCTAssertEqual(parsed.invalid, ["不是网址"])
        XCTAssertTrue(WebURLImportPolicy.invalidMessage(tokens: parsed.invalid).contains("不是网址"))
    }

    func testURLBatch_laterURLsStillOfferSkipRemaining() {
        let parsed = WebURLImportPolicy.parse("https://a.example/1;https://b.example/2")
        let pendingAfterCurrent = parsed.urls.count - 1
        XCTAssertTrue(ImportConflictPolicy.showsSkipRemaining(pendingCount: pendingAfterCurrent))
        XCTAssertFalse(ImportConflictPolicy.shouldPrompt(skipRemainingDuplicates: true))
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

    func testPasteBody_rejectsWhitespaceOnly() {
        XCTAssertFalse(PasteTextImportPolicy.hasImportableBody(" \n\t"))
        XCTAssertTrue(PasteTextImportPolicy.hasImportableBody("标题\n正文"))
    }
}
