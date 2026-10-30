import XCTest
@testable import Lumina

final class OriginalTextBlocksTests: XCTestCase {
    func testParsesGFMTableWithHeader() {
        let text = """
        前文

        | 名 | 值 |
        | --- | --- |
        | 甲 | 一 |

        后文
        """
        let blocks = OriginalTextBlockLayout.parseTextAndTables(text)
        XCTAssertEqual(blocks.count, 3)
        guard case .text(let before) = blocks[0] else { return XCTFail("before") }
        guard case .table(let table) = blocks[1] else { return XCTFail("table") }
        guard case .text(let after) = blocks[2] else { return XCTFail("after") }
        XCTAssertTrue(before.contains("前文"))
        XCTAssertEqual(table.header, ["名", "值"])
        XCTAssertEqual(table.rows, [["甲", "一"]])
        XCTAssertTrue(after.contains("后文"))
    }

    func testParsesLegacyPipeRows() {
        let text = """
        甲 | 乙
        丙 | 丁
        """
        let blocks = OriginalTextBlockLayout.parseTextAndTables(text)
        XCTAssertEqual(blocks.count, 1)
        guard case .table(let table) = blocks[0] else { return XCTFail("table") }
        XCTAssertEqual(table.header, ["甲", "乙"])
        XCTAssertEqual(table.rows, [["丙", "丁"]])
    }

    func testSingleLegacyPipeLineStaysProse() {
        let blocks = OriginalTextBlockLayout.parseTextAndTables("a | b 不是表")
        XCTAssertEqual(blocks.count, 1)
        guard case .text(let prose) = blocks[0] else { return XCTFail("prose") }
        XCTAssertEqual(prose, "a | b 不是表")
    }

    func testEscapedPipeInGFMCell() {
        let blocks = OriginalTextBlockLayout.parseTextAndTables("| a\\|b | c |\n| --- | --- |")
        guard case .table(let table) = blocks.first else { return XCTFail("table") }
        XCTAssertEqual(table.header, ["a|b", "c"])
    }

    func testCombinesIllustrationsAndTables() {
        let illustrations = [
            SegmentIllustration(
                asset_id: "img1",
                char_offset: 2,
                alt: nil,
                url: nil,
                width: 200,
                height: 100,
                mime: nil
            )
        ]
        let text = """
        ab
        | A | B |
        | --- | --- |
        | 1 | 2 |
        """
        let parts = OriginalTextBlockLayout.parts(text: text, illustrations: illustrations)
        XCTAssertTrue(parts.contains { if case .image = $0 { return true }; return false })
        XCTAssertTrue(parts.contains { if case .table = $0 { return true }; return false })
    }

    func testIllustrationAspectRatioPolicy() {
        let ratio = OriginalIllustrationLayoutPolicy.aspectRatio(width: 200, height: 100)
        XCTAssertNotNil(ratio)
        XCTAssertEqual(Double(ratio!), 2.0, accuracy: 0.001)
        XCTAssertNil(OriginalIllustrationLayoutPolicy.aspectRatio(width: 0, height: 10))
        XCTAssertEqual(OriginalIllustrationLayoutPolicy.maxHeight, 420)
    }
}
