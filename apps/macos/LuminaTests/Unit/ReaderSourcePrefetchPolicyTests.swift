import XCTest
@testable import Lumina

final class ReaderSourcePrefetchPolicyTests: XCTestCase {
    func testNeighbourOrder_centerFirstThenNearest() {
        let sorted = Array(0..<20)
        XCTAssertEqual(
            ReaderSourcePrefetchPolicy.neighbourOrder(center: 10, radius: 2, sortedIdxs: sorted),
            [10, 9, 11, 8, 12]
        )
        XCTAssertEqual(
            ReaderSourcePrefetchPolicy.neighbourOrder(center: 0, radius: 2, sortedIdxs: sorted),
            [0, 1, 2]
        )
        XCTAssertEqual(
            ReaderSourcePrefetchPolicy.neighbourOrder(center: 99, radius: 2, sortedIdxs: sorted),
            []
        )
    }

    func testDebounceAndCoalesceDelaysArePositiveAndDebounceIsLonger() {
        XCTAssertGreaterThan(ReaderSourcePrefetchPolicy.debounceNanoseconds, 0)
        XCTAssertGreaterThan(ReaderSourcePrefetchPolicy.publishCoalesceNanoseconds, 0)
        XCTAssertGreaterThan(
            ReaderSourcePrefetchPolicy.debounceNanoseconds,
            ReaderSourcePrefetchPolicy.publishCoalesceNanoseconds
        )
    }

    func testReaderDebouncesSourcePrefetchOnTopSegmentChange() throws {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let reader = try String(
            contentsOf: macosRoot.appendingPathComponent("Lumina/Features/Reader/ReaderView.swift"),
            encoding: .utf8
        )
        guard
            let start = reader.range(of: ".onChange(of: topSegmentIdx)"),
            let end = reader.range(
                of: ".onPreferenceChange(ReaderGlobalFrameKey.self)",
                range: start.lowerBound..<reader.endIndex
            )
        else {
            return XCTFail("missing topSegmentIdx onChange")
        }
        let block = String(reader[start.lowerBound..<end.lowerBound])
        XCTAssertTrue(
            block.contains("scheduleVisiblePrefetch"),
            "topSegmentIdx must debounce hydrate/source fan-out"
        )
        XCTAssertFalse(
            block.contains("prefetchSources(around:"),
            "must not call prefetchSources synchronously on every pin tick"
        )
    }

    func testPrefetchSourcesSerializesLikeSummaries() throws {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let reader = try String(
            contentsOf: macosRoot.appendingPathComponent("Lumina/Features/Reader/ReaderView.swift"),
            encoding: .utf8
        )
        guard
            let start = reader.range(of: "func prefetchSources(around idx: Int"),
            let end = reader.range(
                of: "\n    func canNavigateSegment(",
                range: start.lowerBound..<reader.endIndex
            )
        else {
            return XCTFail("missing prefetchSources")
        }
        let body = String(reader[start.lowerBound..<end.lowerBound])
        XCTAssertTrue(body.contains("sourcePrefetchTask?.cancel()"))
        XCTAssertTrue(body.contains("ReaderSourcePrefetchPolicy.neighbourOrder"))
        XCTAssertTrue(body.contains("Task(priority: .utility)"))
        XCTAssertTrue(body.contains("for neighbour in neighbours"))
        XCTAssertFalse(
            body.contains("for i in start...end"),
            "must not fan out every getSegment at once"
        )
    }

    func testSegmentBlockDoesNotSortFullCatalogPerRow() throws {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let reader = try String(
            contentsOf: macosRoot.appendingPathComponent("Lumina/Features/Reader/ReaderView.swift"),
            encoding: .utf8
        )
        guard
            let start = reader.range(of: "private func segmentBlock(for seg: SegmentRow)"),
            let end = reader.range(
                of: "\n    /// The one and only way to move the reader.",
                range: start.lowerBound..<reader.endIndex
            )
        else {
            return XCTFail("missing segmentBlock")
        }
        let body = String(reader[start.lowerBound..<end.lowerBound])
        XCTAssertFalse(
            body.contains(".map(\\.idx).sorted()"),
            "per-row full-catalog sort freezes ~10k-segment books on search-next"
        )
        XCTAssertTrue(body.contains("canNavigateSegment"))
    }

    func testLoadingSourceIndicesAreNotPublished() throws {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let reader = try String(
            contentsOf: macosRoot.appendingPathComponent("Lumina/Features/Reader/ReaderView.swift"),
            encoding: .utf8
        )
        XCTAssertFalse(
            reader.contains("@Published var loadingSourceIndices"),
            "each getSegment start must not republish the whole feed"
        )
        XCTAssertFalse(
            reader.contains("@Published var refreshingSourceIndices"),
            "refresh flags must coalesce through sourceCacheVersion"
        )
        XCTAssertTrue(reader.contains("scheduleSourceUIRefresh"))
    }
}
