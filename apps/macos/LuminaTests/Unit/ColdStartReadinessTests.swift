import XCTest
@testable import Lumina

final class ColdStartReadinessTests: XCTestCase {
    func testProductReadyRequiresEngineDataCacheOnly() {
        var snap = ColdStartPhaseSnapshot(
            engine: .done,
            data: .done,
            cache: .done,
            news: .running
        )
        XCTAssertTrue(ColdStartReadiness.isProductReady(snap))
        snap.cache = .running
        XCTAssertFalse(ColdStartReadiness.isProductReady(snap))
        snap.cache = .done
        snap.news = .failed
        XCTAssertTrue(ColdStartReadiness.isProductReady(snap))
        XCTAssertTrue(ColdStartReadiness.isBootNewsTerminal(.failed))
        XCTAssertFalse(ColdStartReadiness.isBootNewsTerminal(.running))
    }

    func testMergeMarksEngineRunningUntilDone() {
        let pending = ColdStartReadiness.merge(
            engineDone: false,
            data: "pending",
            cache: "pending",
            news: "pending",
            newsDetail: nil
        )
        XCTAssertEqual(pending.engine, .running)
        let ready = ColdStartReadiness.merge(
            engineDone: true,
            data: "done",
            cache: "running",
            news: "pending",
            newsDetail: nil
        )
        XCTAssertEqual(ready.engine, .done)
        XCTAssertEqual(ready.data, .done)
        XCTAssertEqual(ready.cache, .running)
    }

    func testGateRowsExcludeNews() {
        XCTAssertEqual(ColdStartRowKind.allCases, [.engine, .data, .cache])
    }

    func testCacheProgressAndDetailInMergeAndRowLabel() {
        let snap = ColdStartReadiness.merge(
            engineDone: true,
            data: "done",
            cache: "running",
            cacheProgress: 0.45,
            cacheDetail: "恢复书籍状态 (12/48)",
            news: "pending",
            newsDetail: nil
        )
        XCTAssertEqual(snap.cache, .running)
        XCTAssertEqual(snap.cacheProgress, 0.45)
        XCTAssertEqual(snap.cacheDetail, "恢复书籍状态 (12/48)")

        let labelWithDetail = ColdStartReadiness.rowLabel(
            kind: .cache,
            state: .running,
            cacheDetail: snap.cacheDetail
        )
        XCTAssertEqual(labelWithDetail, "缓存加载中 · 恢复书籍状态 (12/48)")

        let labelWithoutDetail = ColdStartReadiness.rowLabel(
            kind: .cache,
            state: .running,
            cacheDetail: nil
        )
        XCTAssertEqual(labelWithoutDetail, "缓存加载中")
    }
}
