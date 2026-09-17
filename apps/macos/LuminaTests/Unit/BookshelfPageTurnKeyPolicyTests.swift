import XCTest
@testable import Lumina

@MainActor
final class BookshelfPageTurnKeyPolicyTests: XCTestCase {
    // MARK: - BookshelfPageTurnKeyPolicy tests

    func testDelta_leftArrow_returnsMinusOne() {
        let delta = BookshelfPageTurnKeyPolicy.delta(
            keyCode: BookshelfPageTurnKeyPolicy.leftArrowKeyCode,
            characters: nil,
            hasModifiers: false,
            isRepeat: false
        )
        XCTAssertEqual(delta, -1)
    }

    func testDelta_rightArrow_returnsPlusOne() {
        let delta = BookshelfPageTurnKeyPolicy.delta(
            keyCode: BookshelfPageTurnKeyPolicy.rightArrowKeyCode,
            characters: nil,
            hasModifiers: false,
            isRepeat: false
        )
        XCTAssertEqual(delta, 1)
    }

    func testDelta_arrowFunctionKeys_unicodeFallback() {
        let leftUnicode = String(UnicodeScalar(0xF702)!)
        let rightUnicode = String(UnicodeScalar(0xF703)!)

        let leftDelta = BookshelfPageTurnKeyPolicy.delta(
            keyCode: 999,
            characters: leftUnicode,
            hasModifiers: false,
            isRepeat: false
        )
        XCTAssertEqual(leftDelta, -1)

        let rightDelta = BookshelfPageTurnKeyPolicy.delta(
            keyCode: 999,
            characters: rightUnicode,
            hasModifiers: false,
            isRepeat: false
        )
        XCTAssertEqual(rightDelta, 1)
    }

    func testDelta_withModifiers_returnsNil() {
        let leftWithMod = BookshelfPageTurnKeyPolicy.delta(
            keyCode: BookshelfPageTurnKeyPolicy.leftArrowKeyCode,
            characters: nil,
            hasModifiers: true,
            isRepeat: false
        )
        XCTAssertNil(leftWithMod)

        let rightWithMod = BookshelfPageTurnKeyPolicy.delta(
            keyCode: BookshelfPageTurnKeyPolicy.rightArrowKeyCode,
            characters: nil,
            hasModifiers: true,
            isRepeat: false
        )
        XCTAssertNil(rightWithMod)
    }

    func testDelta_isRepeat_returnsNil() {
        let leftRepeat = BookshelfPageTurnKeyPolicy.delta(
            keyCode: BookshelfPageTurnKeyPolicy.leftArrowKeyCode,
            characters: nil,
            hasModifiers: false,
            isRepeat: true
        )
        XCTAssertNil(leftRepeat)

        let rightRepeat = BookshelfPageTurnKeyPolicy.delta(
            keyCode: BookshelfPageTurnKeyPolicy.rightArrowKeyCode,
            characters: nil,
            hasModifiers: false,
            isRepeat: true
        )
        XCTAssertNil(rightRepeat)
    }

    func testDelta_otherKeys_returnsNil() {
        // Up arrow: 126, Down arrow: 125, Return: 36, Space: 49
        for code in [UInt16(125), UInt16(126), UInt16(36), UInt16(49), UInt16(0)] {
            let result = BookshelfPageTurnKeyPolicy.delta(
                keyCode: code,
                characters: "a",
                hasModifiers: false,
                isRepeat: false
            )
            XCTAssertNil(result)
        }
    }

    func testBlocksPageTurn_emptyEditableField_allowsPaging() {
        XCTAssertFalse(
            BookshelfPageTurnKeyPolicy.blocksPageTurn(
                isEditableTextInput: true,
                contentIsEmpty: true
            ),
            "autofocused empty「筛选书名」must not swallow ←/→"
        )
        XCTAssertTrue(
            BookshelfPageTurnKeyPolicy.blocksPageTurn(
                isEditableTextInput: true,
                contentIsEmpty: false
            )
        )
        XCTAssertFalse(
            BookshelfPageTurnKeyPolicy.blocksPageTurn(
                isEditableTextInput: false,
                contentIsEmpty: false
            )
        )
    }

    // MARK: - LibraryViewModel paging actions tests

    private func makeBooks(count: Int) -> [BookSummary] {
        (0..<count).map { idx in
            BookSummary(
                id: "book-\(idx)",
                title: "Book \(idx)",
                status: "ready",
                segment_count: 10,
                is_favorite: false,
                category: "科技",
                last_opened_at: nil,
                current_segment_index: nil,
                created_at: nil,
                summary_ready_count: 0,
                summary_total_count: 0,
                summarize_state: "idle",
                readingPercent: nil
            )
        }
    }

    func testSinglePage_cannotTurnPages() {
        let vm = LibraryViewModel()
        vm.books = makeBooks(count: 5)
        vm.pageSize = 10

        XCTAssertEqual(vm.pageCount, 1)
        XCTAssertFalse(vm.canGoPreviousPage)
        XCTAssertFalse(vm.canGoNextPage)

        XCTAssertFalse(vm.previousPage())
        XCTAssertEqual(vm.pageIndex, 0)

        XCTAssertFalse(vm.nextPage())
        XCTAssertEqual(vm.pageIndex, 0)
    }

    func testMultiplePages_boundaryAndNavigation() {
        let vm = LibraryViewModel()
        vm.books = makeBooks(count: 25)
        vm.pageSize = 10

        XCTAssertEqual(vm.pageCount, 3)
        XCTAssertEqual(vm.pageIndex, 0)
        XCTAssertFalse(vm.canGoPreviousPage)
        XCTAssertTrue(vm.canGoNextPage)

        // Previous on first page should fail
        XCTAssertFalse(vm.previousPage())
        XCTAssertEqual(vm.pageIndex, 0)

        // Turn to page 1
        XCTAssertTrue(vm.nextPage())
        XCTAssertEqual(vm.pageIndex, 1)
        XCTAssertTrue(vm.canGoPreviousPage)
        XCTAssertTrue(vm.canGoNextPage)

        // Turn to page 2 (last page)
        XCTAssertTrue(vm.nextPage())
        XCTAssertEqual(vm.pageIndex, 2)
        XCTAssertTrue(vm.canGoPreviousPage)
        XCTAssertFalse(vm.canGoNextPage)

        // Next on last page should fail
        XCTAssertFalse(vm.nextPage())
        XCTAssertEqual(vm.pageIndex, 2)

        // Turn back to page 1
        XCTAssertTrue(vm.previousPage())
        XCTAssertEqual(vm.pageIndex, 1)

        // Turn back to page 0
        XCTAssertTrue(vm.previousPage())
        XCTAssertEqual(vm.pageIndex, 0)
        XCTAssertFalse(vm.canGoPreviousPage)
    }

    func testBookshelfView_clearsTitleFilterAutofocusAndEmptyFieldAllowsArrows() throws {
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
        XCTAssertTrue(bookshelf.contains("@FocusState private var titleFilterFocused"))
        XCTAssertTrue(bookshelf.contains(".focused($titleFilterFocused)"))
        XCTAssertTrue(
            bookshelf.contains("titleFilterFocused = false"),
            "startup must clear macOS TextField autofocus so ←/→ can page"
        )
        XCTAssertTrue(bookshelf.contains("blocksPageTurn("))
        XCTAssertTrue(
            bookshelf.contains("contentIsEmpty: textView.string.isEmpty")
                || bookshelf.contains("contentIsEmpty: field.stringValue.isEmpty")
        )
    }
}
