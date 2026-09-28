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

    func testLocateKind_sameSegmentCachedIsHighlightOnly() {
        XCTAssertEqual(
            OriginalSearchHighlight.locateKind(
                hitSegmentIndex: 12,
                currentSegmentIndex: 12,
                contentModeIsOriginal: true,
                sourceCached: true
            ),
            .highlightOnly
        )
        XCTAssertEqual(
            OriginalSearchHighlight.locateKind(
                hitSegmentIndex: 12,
                currentSegmentIndex: 12,
                contentModeIsOriginal: true,
                sourceCached: false
            ),
            .navigateAndFetch
        )
        XCTAssertEqual(
            OriginalSearchHighlight.locateKind(
                hitSegmentIndex: 12,
                currentSegmentIndex: 11,
                contentModeIsOriginal: true,
                sourceCached: true
            ),
            .navigateAndFetch
        )
        XCTAssertEqual(
            OriginalSearchHighlight.locateKind(
                hitSegmentIndex: 12,
                currentSegmentIndex: 12,
                contentModeIsOriginal: false,
                sourceCached: true
            ),
            .navigateAndFetch
        )
    }

    func testStepCoalesceDelayIsPositiveAndShort() {
        XCTAssertGreaterThan(OriginalSearchHighlight.stepCoalesceNanoseconds, 0)
        XCTAssertLessThan(
            OriginalSearchHighlight.stepCoalesceNanoseconds,
            ReaderSourcePrefetchPolicy.debounceNanoseconds
        )
        XCTAssertGreaterThan(
            OriginalSearchHighlight.seekPrefetchSuppressNanoseconds,
            OriginalSearchHighlight.stepCoalesceNanoseconds
        )
    }

    func testAllowsNeighbourSourceFetch_onlyTargetDuringSeek() {
        XCTAssertTrue(
            OriginalSearchHighlight.allowsNeighbourSourceFetch(
                seekTarget: nil,
                segmentIndex: 10
            )
        )
        XCTAssertTrue(
            OriginalSearchHighlight.allowsNeighbourSourceFetch(
                seekTarget: 1542,
                segmentIndex: 1542
            )
        )
        XCTAssertFalse(
            OriginalSearchHighlight.allowsNeighbourSourceFetch(
                seekTarget: 1542,
                segmentIndex: 1543
            )
        )
    }

    func testReaderSameSegmentSearchSkipsNavigate() throws {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let reader = try String(
            contentsOf: macosRoot.appendingPathComponent("Lumina/Features/Reader/ReaderView.swift"),
            encoding: .utf8
        )
        guard
            let start = reader.range(of: "private func stepOriginalSearch(_ delta: Int)"),
            let end = reader.range(
                of: "private func scheduleLocateOriginalSearchHit()",
                range: start.lowerBound..<reader.endIndex
            )
        else {
            return XCTFail("missing stepOriginalSearch")
        }
        let body = String(reader[start.lowerBound..<end.lowerBound])
        XCTAssertTrue(body.contains("locateKind"))
        XCTAssertTrue(body.contains(".highlightOnly"))
        XCTAssertTrue(body.contains("scheduleLocateOriginalSearchHit"))
    }

    func testReaderSearchLocateSuppressesNeighbourFanOut() throws {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let reader = try String(
            contentsOf: macosRoot.appendingPathComponent("Lumina/Features/Reader/ReaderView.swift"),
            encoding: .utf8
        )
        XCTAssertTrue(reader.contains("originalSearchFocusSegment"))
        XCTAssertTrue(reader.contains("search-focus-"))
        XCTAssertTrue(reader.contains("usesFocusFeed"))
        XCTAssertTrue(reader.contains("retainSourceCacheOnly"))
        XCTAssertTrue(reader.contains("usesLightweightOriginalText"))
        XCTAssertTrue(reader.contains("LuminaTextLayoutGeneration.bump"))
        guard
            let start = reader.range(of: "private func locateOriginalSearchHit()"),
            let end = reader.range(
                of: "private func beginOriginalSearchSeek(target:",
                range: start.lowerBound..<reader.endIndex
            )
        else {
            return XCTFail("missing locateOriginalSearchHit")
        }
        let body = String(reader[start.lowerBound..<end.lowerBound])
        XCTAssertTrue(body.contains("beginOriginalSearchSeek"))
        XCTAssertTrue(
            body.contains("usesFocusFeed"),
            "locate must skip full-ForEach navigate while focus feed is active"
        )
    }

    func testUsesFocusFeedWhenExpandedWithHits() {
        XCTAssertTrue(OriginalSearchHighlight.usesFocusFeed(expanded: true, hitCount: 3))
        XCTAssertFalse(OriginalSearchHighlight.usesFocusFeed(expanded: false, hitCount: 3))
        XCTAssertFalse(OriginalSearchHighlight.usesFocusFeed(expanded: true, hitCount: 0))
    }

    func testSearchFocusAttributedHighlight() {
        let text = "甲乙丙丁"
        let ns = text as NSString
        let range = NSRange(location: 0, length: 2)
        let attributed = SearchFocusOriginalText.attributed(
            text: text,
            highlightUTF16: range,
            fontSize: 14,
            foreground: .primary,
            highlightColor: .yellow
        )
        XCTAssertEqual(String(attributed.characters), text)
        XCTAssertEqual(ns.substring(with: range), "甲乙")
    }

    func testSearchRevealUsesBoundedGlyphLayout() throws {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let source = try String(
            contentsOf: macosRoot.appendingPathComponent(
                "Lumina/Features/Shared/SelectableTextView.swift"
            ),
            encoding: .utf8
        )
        guard let start = source.range(of: "private static func reveal("),
              let end = source.range(
                of: "// MARK: - AppKit views",
                range: start.lowerBound..<source.endIndex
              )
        else {
            return XCTFail("missing reveal()")
        }
        let body = String(source[start.lowerBound..<end.lowerBound])
        XCTAssertTrue(body.contains("ensureLayout(forGlyphRange:"))
        XCTAssertTrue(body.contains("ensureGlyphs(forCharacterRange:"))
        XCTAssertFalse(
            body.contains("ensureLayout(for: textContainer)"),
            "search-next must not full-container ensureLayout long CJK"
        )
    }
}
