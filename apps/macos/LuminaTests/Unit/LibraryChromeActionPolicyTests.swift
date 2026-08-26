import XCTest
@testable import Lumina

final class LibraryChromeActionPolicyTests: XCTestCase {
    func testAllReadingAndBrowseLayouts_haveUniqueToolbarActions() {
        for hasBook in [false, true] {
            let surfaces = LibraryChromeActionPolicy.windowToolbarSurfaces(
                hasSelectedBook: hasBook
            )
            XCTAssertTrue(
                LibraryChromeActionPolicy.duplicateActions(among: surfaces).isEmpty,
                "layout book=\(hasBook)"
            )
        }
    }

    func testReaderDoesNotExposeARecentsChromeAction() {
        XCTAssertFalse(
            LibraryChromeActionPolicy.toolbarActions(on: .reader).contains(where: {
                $0.rawValue == "recents"
            })
        )
        XCTAssertFalse(LibraryChromeAction.allCases.map(\.rawValue).contains("recents"))
    }

    func testReaderOwnsSingleImportAndBookshelfActions() {
        let reader = LibraryChromeActionPolicy.toolbarActions(on: .reader)
        let bookshelf = LibraryChromeActionPolicy.toolbarActions(on: .bookshelf)
        XCTAssertTrue(reader.contains(.importBook))
        XCTAssertTrue(reader.contains(.bookshelf))
        XCTAssertTrue(reader.contains(.segmentList))
        XCTAssertEqual(reader.intersection(bookshelf), [])
    }

    func testLibraryContextMenu_alwaysOffersResegment() {
        let ready = BookSummary(
            id: "b1", title: "Ready", status: "reading", segment_count: 4
        )
        XCTAssertEqual(
            LibraryBookContextMenuPolicy.actions(for: ready),
            [.favorite, .rename, .reclassify, .resegment, .exportMarkdown, .delete]
        )
        XCTAssertTrue(LibraryBookContextMenuPolicy.isEnabled(.resegment, for: ready))

        let summarizing = BookSummary(
            id: "b2",
            title: "Summarizing",
            status: "reading",
            segment_count: 4,
            summary_ready_count: 1,
            summary_total_count: 4,
            summarize_state: "running"
        )
        XCTAssertTrue(
            LibraryBookContextMenuPolicy.actions(for: summarizing).contains(.resegment)
        )
        XCTAssertTrue(LibraryBookContextMenuPolicy.isEnabled(.resegment, for: summarizing))

        let processing = BookSummary(
            id: "b3", title: "Busy", status: "processing", segment_count: 4
        )
        XCTAssertTrue(
            LibraryBookContextMenuPolicy.actions(for: processing).contains(.resegment)
        )
        XCTAssertFalse(LibraryBookContextMenuPolicy.isEnabled(.resegment, for: processing))
    }

    func testLibraryContextMenu_alwaysOffersRename() {
        let ready = BookSummary(
            id: "b1", title: "Ready", status: "reading", segment_count: 4
        )
        XCTAssertTrue(LibraryBookContextMenuPolicy.actions(for: ready).contains(.rename))
        XCTAssertTrue(LibraryBookContextMenuPolicy.isEnabled(.rename, for: ready))

        let processing = BookSummary(
            id: "b3", title: "Busy", status: "processing", segment_count: 0
        )
        XCTAssertTrue(LibraryBookContextMenuPolicy.actions(for: processing).contains(.rename))
        XCTAssertTrue(LibraryBookContextMenuPolicy.isEnabled(.rename, for: processing))
    }

    func testBookDisplayTitle_normalizedRejectsBlank() {
        XCTAssertEqual(BookDisplayTitle.normalized("  新书名  "), "新书名")
        XCTAssertNil(BookDisplayTitle.normalized("   "))
        XCTAssertNil(BookDisplayTitle.normalized(""))
    }

    func testLibrarySummarizeUsesSplitMenuNotContextMenu() throws {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let bookshelf = try String(
            contentsOf: macosRoot.appendingPathComponent(
                "Lumina/Features/Library/BookshelfView.swift"
            ),
            encoding: .utf8
        )
        let toolbar = bookshelf
            .components(separatedBy: "private var toolbarContent")
            .last?
            .components(separatedBy: "private var bookshelfControls")
            .first ?? ""
        XCTAssertTrue(toolbar.contains("SummarizeChevronSplit(title: \"全部开始摘要\")"))
        XCTAssertTrue(toolbar.contains(".popover(isPresented: $showSummarizePopover"))
        XCTAssertTrue(toolbar.contains("高级摘要（仅未摘要）"))
        XCTAssertTrue(toolbar.contains("showAdvancedStartConfirm"))
        XCTAssertTrue(toolbar.contains("全部停止摘要"))
        XCTAssertTrue(
            bookshelf.contains("将用高级模型补齐尚未摘要的段落"),
            "advanced start must confirm extra cost and no overwrite"
        )
        XCTAssertTrue(
            toolbar.contains("点旁边箭头才展开高级（悬停不弹出）")
        )
        XCTAssertFalse(
            toolbar.contains("} primaryAction: {"),
            "nested Menu+primaryAction opens advanced on hover"
        )
        XCTAssertFalse(
            toolbar.contains(".contextMenu"),
            "bookshelf toolbar must not hide advanced behind right-click"
        )

        let selection = try String(
            contentsOf: macosRoot.appendingPathComponent(
                "Lumina/Features/Library/LibrarySelectionToolbar.swift"
            ),
            encoding: .utf8
        )
        let summarize = selection
            .components(separatedBy: "private var summarizeMenu")
            .last?
            .components(separatedBy: "private var deleteButton")
            .first ?? ""
        XCTAssertTrue(summarize.contains("SummarizeChevronSplit("))
        XCTAssertTrue(summarize.contains(".popover(isPresented: $showSummarizePopover"))
        XCTAssertTrue(summarize.contains("showAdvancedStartConfirm"))
        XCTAssertFalse(summarize.contains(".contextMenu"))
        XCTAssertFalse(
            summarize.contains("} primaryAction: {"),
            "nested Menu+primaryAction opens advanced on hover"
        )
        XCTAssertFalse(
            summarize.contains(".menuStyle"),
            "outer 摘要 is a Button+popover; do not restyle an inner Menu with buttonStyle"
        )

        let windowsRoot = macosRoot
            .deletingLastPathComponent()
            .appendingPathComponent("windows/Lumina/Features")
        let libraryXaml = try String(
            contentsOf: windowsRoot.appendingPathComponent("Library/LibraryPage.xaml"),
            encoding: .utf8
        )
        XCTAssertTrue(libraryXaml.contains("SplitButton"))
        XCTAssertTrue(libraryXaml.contains("Content=\"开始摘要\""))
        XCTAssertTrue(libraryXaml.contains("高级摘要（仅未摘要）"))
        XCTAssertFalse(libraryXaml.contains("Button.ContextFlyout"))
        let libraryCs = try String(
            contentsOf: windowsRoot.appendingPathComponent("Library/LibraryPage.xaml.cs"),
            encoding: .utf8
        )
        XCTAssertTrue(libraryCs.contains("ConfirmAdvancedStartAsync"))

        let readerXaml = try String(
            contentsOf: windowsRoot.appendingPathComponent("Reader/ReaderPage.xaml"),
            encoding: .utf8
        )
        XCTAssertTrue(readerXaml.contains("Label=\"摘要\""))
        XCTAssertTrue(readerXaml.contains("SplitButton"))
        XCTAssertTrue(readerXaml.contains("Content=\"开始摘要\""))
        XCTAssertTrue(readerXaml.contains("Content=\"重新摘要整书\""))
        XCTAssertTrue(readerXaml.contains("Content=\"停止摘要\""))
        XCTAssertFalse(readerXaml.contains("AppBarButton.ContextFlyout"))
        let readerCs = try String(
            contentsOf: windowsRoot.appendingPathComponent("Reader/ReaderPage.xaml.cs"),
            encoding: .utf8
        )
        XCTAssertTrue(readerCs.contains("ConfirmAdvancedStartAsync"))
        XCTAssertTrue(readerCs.contains("ConfirmAndRegenerateAsync"))
        XCTAssertTrue(readerCs.contains("RegenerateNormal_Click"))
    }

    func testLibraryOpenBook_allowsReadyAndSegmenting_blocksIngestFailed() {
        let ready = BookSummary(
            id: "ready", title: "Ready", status: "reading", segment_count: 4
        )
        let segmenting = BookSummary(
            id: "busy",
            title: "Busy",
            status: "processing",
            segment_count: 0,
            summarize_state: "segmenting"
        )
        let failed = BookSummary(
            id: "fail", title: "Fail", status: "error", segment_count: 0
        )
        XCTAssertTrue(ready.canOpenInReader)
        XCTAssertFalse(ready.isSegmenting)
        XCTAssertTrue(segmenting.isSegmenting)
        XCTAssertTrue(segmenting.canOpenInReader)
        XCTAssertTrue(failed.isIngestFailed)
        XCTAssertFalse(failed.canOpenInReader)
    }

    func testLibraryOpenBook_doesNotSwallowSegmentingClicks() throws {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let bookshelf = try String(
            contentsOf: macosRoot.appendingPathComponent(
                "Lumina/Features/Library/BookshelfView.swift"
            ),
            encoding: .utf8
        )
        XCTAssertFalse(
            bookshelf.contains("if book.isSegmenting { return }"),
            "tapping a 分段中 book must open the reader progress page"
        )
        XCTAssertTrue(bookshelf.contains("canOpenInReader"))

        let card = try String(
            contentsOf: macosRoot.appendingPathComponent(
                "Lumina/Features/Library/BookCard.swift"
            ),
            encoding: .utf8
        )
        let row = try String(
            contentsOf: macosRoot.appendingPathComponent(
                "Lumina/Features/Library/BookRow.swift"
            ),
            encoding: .utf8
        )
        XCTAssertFalse(
            card.contains("ProgressView()"),
            "indeterminate ProgressView on a card steals clicks from other books"
        )
        XCTAssertFalse(row.contains("ProgressView()"))
        XCTAssertTrue(card.contains("LibraryIngestMeter"))

        let client = try String(
            contentsOf: macosRoot.appendingPathComponent(
                "Lumina/Services/CoreClient.swift"
            ),
            encoding: .utf8
        )
        XCTAssertTrue(client.contains("sseSession"))
        XCTAssertTrue(client.contains("Self.sseSession.bytes"))
        let subscribe = client
            .components(separatedBy: "func subscribeEvents")
            .last?
            .components(separatedBy: "private static let maxConnectionAttempts")
            .first ?? ""
        XCTAssertTrue(subscribe.contains("Self.sseSession.bytes"))
        XCTAssertFalse(
            subscribe.contains("session.bytes"),
            "ingest SSE must not share URLSession.shared with openBook"
        )

        let windowsLibrary = try String(
            contentsOf: macosRoot
                .deletingLastPathComponent()
                .appendingPathComponent(
                    "windows/Lumina/Features/Library/LibraryPage.xaml.cs"
                ),
            encoding: .utf8
        )
        XCTAssertFalse(windowsLibrary.contains("if (book.IsSegmenting || book.IsIngestFailed)"))
        XCTAssertTrue(windowsLibrary.contains("CanOpenInReader"))
    }
}
