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
    var cacheProgress: Double?
    var cacheDetail: String?
    /// Background boot news (not part of the gate).
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

    static func rowLabel(
        kind: ColdStartRowKind,
        state: ColdStartPhaseState,
        cacheDetail: String? = nil
    ) -> String {
        switch kind {
        case .engine:
            return state == .done ? "启动完毕" : "引擎启动中"
        case .data:
            return state == .done ? "准备完毕" : "数据准备中"
        case .cache:
            if state == .done { return "加载完毕" }
            if let detail = cacheDetail, !detail.isEmpty {
                return "缓存加载中 · \(detail)"
            }
            return "缓存加载中"
        }
    }
}

enum ColdStartRowKind: CaseIterable {
    case engine, data, cache
}
