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

    func testDetailRevealPolicy() {
        XCTAssertEqual(ColdStartReadiness.detailRevealAfterSeconds, 10)
        XCTAssertFalse(ColdStartReadiness.shouldRevealTechnicalDetail(elapsedSeconds: 9.9))
        XCTAssertTrue(ColdStartReadiness.shouldRevealTechnicalDetail(elapsedSeconds: 10))
    }

    func testTechnicalDetailDerivesFromInternalPhase() {
        let engine = ColdStartReadiness.merge(
            engineDone: false,
            data: "pending",
            cache: "pending",
            news: "pending",
            newsDetail: nil
        )
        XCTAssertEqual(ColdStartReadiness.technicalDetail(engine), "正在启动引擎")

        let data = ColdStartReadiness.merge(
            engineDone: true,
            data: "running",
            cache: "pending",
            news: "pending",
            newsDetail: nil
        )
        XCTAssertEqual(ColdStartReadiness.technicalDetail(data), "正在准备阅读数据")

        let cache = ColdStartReadiness.merge(
            engineDone: true,
            data: "done",
            cache: "running",
            cacheProgress: 0.45,
            cacheDetail: "恢复书籍状态 (12/48)",
            news: "pending",
            newsDetail: nil
        )
        XCTAssertEqual(
            ColdStartReadiness.technicalDetail(cache),
            "恢复书籍状态 (12/48)"
        )

        let cachePlain = ColdStartReadiness.merge(
            engineDone: true,
            data: "done",
            cache: "running",
            news: "pending",
            newsDetail: nil
        )
        XCTAssertEqual(ColdStartReadiness.technicalDetail(cachePlain), "正在加载缓存")

        XCTAssertEqual(
            ColdStartReadiness.technicalDetail(cachePlain, launchError: "无法连接"),
            "无法连接"
        )
    }
}
