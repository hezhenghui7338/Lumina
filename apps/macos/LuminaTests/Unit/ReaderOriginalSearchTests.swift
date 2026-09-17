import XCTest
@testable import Lumina

final class ReaderOriginalSearchTests: XCTestCase {
    func testNSRange_fromUTF16Offsets() {
        let text = "学而😊时习" as NSString
        let start = 2
        let end = 4
        let range = OriginalSearchHighlight.nsRange(
            startUTF16: start,
            endUTF16: end,
            inUTF16Length: text.length
        )
        XCTAssertEqual(range?.location, 2)
        XCTAssertEqual(range?.length, 2)
        XCTAssertEqual(text.substring(with: range!), "😊")
    }

    func testNSRange_rejectsOverflow() {
        XCTAssertNil(
            OriginalSearchHighlight.nsRange(
                startUTF16: 0,
                endUTF16: 4,
                inUTF16Length: 3
            )
        )
        XCTAssertNil(
            OriginalSearchHighlight.nsRange(
                startUTF16: 2,
                endUTF16: 2,
                inUTF16Length: 5
            )
        )
    }

    func testSteppedIndex_wraps() {
        XCTAssertEqual(OriginalSearchHighlight.steppedIndex(current: 0, delta: -1, count: 3), 2)
        XCTAssertEqual(OriginalSearchHighlight.steppedIndex(current: 2, delta: 1, count: 3), 0)
        XCTAssertNil(OriginalSearchHighlight.steppedIndex(current: 0, delta: 1, count: 0))
    }

    func testNavigate_loadsMoreWhenTruncatedAtEnd() {
        XCTAssertEqual(
            OriginalSearchHighlight.navigate(current: 79, delta: 1, count: 80, truncated: true),
            .loadMore
        )
        XCTAssertEqual(
            OriginalSearchHighlight.navigate(current: 79, delta: 1, count: 80, truncated: false),
            .step(to: 0)
        )
        XCTAssertEqual(
            OriginalSearchHighlight.navigate(current: 0, delta: -1, count: 80, truncated: true),
            .step(to: 79)
        )
        XCTAssertEqual(
            OriginalSearchHighlight.navigate(current: 10, delta: 1, count: 80, truncated: true),
            .step(to: 11)
        )
    }

    func testStatusLabel() {
        XCTAssertEqual(
            OriginalSearchHighlight.statusLabel(index: 0, count: 0, truncated: false),
            "无匹配"
        )
        XCTAssertEqual(
            OriginalSearchHighlight.statusLabel(index: 1, count: 12, truncated: false),
            "2/12"
        )
        XCTAssertEqual(
            OriginalSearchHighlight.statusLabel(index: 0, count: 80, truncated: true),
            "1/80+"
        )
    }

    func testOriginalSearchResponse_decodesWithoutRawText() throws {
        let json = """
        {"query":"学而","hits":[{"segment_index":4,"start":10,"end":12,"start_utf16":10,"end_utf16":12,"snippet":"子曰：[学而]时习"}],"truncated":false}
        """.data(using: .utf8)!
        let resp = try JSONDecoder().decode(OriginalSearchResponse.self, from: json)
        XCTAssertEqual(resp.hits.count, 1)
        XCTAssertEqual(resp.hits[0].segment_index, 4)
        XCTAssertEqual(resp.hits[0].start_utf16, 10)
        XCTAssertFalse(resp.truncated)
        let dumped = String(data: json, encoding: .utf8)!
        XCTAssertFalse(dumped.contains("raw_text"))
    }
}
