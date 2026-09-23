import Foundation

/// Internal cold-start phase (PRD §3.5; not shown as a checklist).
enum ColdStartPhaseState: String, Equatable {
    case pending
    case running
    case done
    case failed
}

struct ColdStartPhaseSnapshot: Equatable {
    var engine: ColdStartPhaseState = .pending
    var data: ColdStartPhaseState = .pending
    var cache: ColdStartPhaseState = .pending
    var cacheProgress: Double?
    var cacheDetail: String?
    /// Background boot news (not part of product-ready).
    var news: ColdStartPhaseState = .pending
    var newsDetail: String?

    static let initial = ColdStartPhaseSnapshot()
}

/// Pure cold-start gate decisions (unit-testable).
enum ColdStartReadiness {
    static let statusPollIntervalNanoseconds: UInt64 = 100_000_000
    /// After this many seconds, reveal one soft technical line (PRD §3.5).
    static let detailRevealAfterSeconds: TimeInterval = 10

    static func phaseState(from raw: String?) -> ColdStartPhaseState {
        switch (raw ?? "").lowercased() {
        case "running": return .running
        case "done": return .done
        case "failed": return .failed
        default: return .pending
        }
    }

    /// Engine is local; data/cache/(background) news come from GET /startup/status.
    static func merge(
        engineDone: Bool,
        data: String?,
        cache: String?,
        cacheProgress: Double? = nil,
        cacheDetail: String? = nil,
        news: String?,
        newsDetail: String? = nil
    ) -> ColdStartPhaseSnapshot {
        ColdStartPhaseSnapshot(
            engine: engineDone ? .done : .running,
            data: phaseState(from: data),
            cache: phaseState(from: cache),
            cacheProgress: cacheProgress,
            cacheDetail: cacheDetail,
            news: phaseState(from: news),
            newsDetail: newsDetail
        )
    }

    /// Product-ready after engine → data → cache (news is background, §3.5 / §5.8).
    static func isProductReady(_ snapshot: ColdStartPhaseSnapshot) -> Bool {
        snapshot.engine == .done
            && snapshot.data == .done
            && snapshot.cache == .done
    }

    static func isBootNewsTerminal(_ state: ColdStartPhaseState) -> Bool {
        state == .done || state == .failed
    }

    static func shouldRevealTechnicalDetail(elapsedSeconds: TimeInterval) -> Bool {
        elapsedSeconds >= detailRevealAfterSeconds
    }

    /// One soft line derived from the current internal phase (never a multi-step list).
    static func technicalDetail(
        _ snapshot: ColdStartPhaseSnapshot,
        launchError: String? = nil
    ) -> String {
        if let launchError, !launchError.isEmpty {
            return launchError
        }
        if snapshot.engine != .done {
            return "正在启动引擎"
        }
        if snapshot.data != .done {
            return "正在准备阅读数据"
        }
        if let detail = snapshot.cacheDetail, !detail.isEmpty {
            return detail
        }
        return "正在加载缓存"
    }
}
