import XCTest
@testable import Lumina

final class ColdStartReadinessTests: XCTestCase {
    func testProductReadyRequiresEngineDataCacheAndTerminalNews() {
        var snap = ColdStartPhaseSnapshot(
            engine: .done,
            data: .done,
            cache: .done,
            news: .running
        )
        XCTAssertFalse(ColdStartReadiness.isProductReady(snap))
        snap.news = .done
        XCTAssertTrue(ColdStartReadiness.isProductReady(snap))
        snap.news = .failed
        XCTAssertTrue(ColdStartReadiness.isProductReady(snap))
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

    func testNewsFailedLabel() {
        let label = ColdStartReadiness.rowLabel(
            kind: .news,
            state: .failed,
            newsFailed: true
        )
        XCTAssertEqual(label, "更新完毕（未全部成功）")
    }
}
