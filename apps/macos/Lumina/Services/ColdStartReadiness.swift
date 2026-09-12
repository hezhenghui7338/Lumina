import Foundation

/// One cold-start checklist row (PRD §3.5).
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
    var news: ColdStartPhaseState = .pending
    var newsDetail: String?

    static let initial = ColdStartPhaseSnapshot()
}

/// Pure cold-start gate decisions (unit-testable).
enum ColdStartReadiness {
    static let statusPollIntervalNanoseconds: UInt64 = 100_000_000

    static func phaseState(from raw: String?) -> ColdStartPhaseState {
        switch (raw ?? "").lowercased() {
        case "running": return .running
        case "done": return .done
        case "failed": return .failed
        default: return .pending
        }
    }

    /// Engine is local; data/cache/news come from GET /startup/status.
    static func merge(
        engineDone: Bool,
        data: String?,
        cache: String?,
        news: String?,
        newsDetail: String?
    ) -> ColdStartPhaseSnapshot {
        ColdStartPhaseSnapshot(
            engine: engineDone ? .done : .running,
            data: phaseState(from: data),
            cache: phaseState(from: cache),
            news: phaseState(from: news),
            newsDetail: newsDetail
        )
    }

    /// News `failed` still unlocks the main UI (offline / timeout).
    static func isProductReady(_ snapshot: ColdStartPhaseSnapshot) -> Bool {
        snapshot.engine == .done
            && snapshot.data == .done
            && snapshot.cache == .done
            && (snapshot.news == .done || snapshot.news == .failed)
    }

    static func rowLabel(kind: ColdStartRowKind, state: ColdStartPhaseState, newsFailed: Bool) -> String {
        switch kind {
        case .engine:
            return state == .done ? "启动完毕" : "引擎启动中"
        case .data:
            return state == .done ? "准备完毕" : "数据准备中"
        case .cache:
            return state == .done ? "加载完毕" : "缓存加载中"
        case .news:
            if state == .done { return "更新完毕" }
            if state == .failed || newsFailed { return "更新完毕（未全部成功）" }
            return "资讯更新中"
        }
    }
}

enum ColdStartRowKind: CaseIterable {
    case engine, data, cache, news
}
