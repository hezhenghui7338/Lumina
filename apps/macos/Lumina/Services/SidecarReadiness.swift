import Foundation

enum SidecarEngineStatus: Equatable {
    case starting
    case running
    case stopped
    case failed
}

/// Pure readiness decisions for SidecarManager (unit-testable).
enum SidecarReadiness {
    /// Must match lumina-core `CHUNKER_VERSION`. A mismatch never marks the sidecar ready,
    /// so library / news / settings all refuse to load.
    static let expectedChunkerVersion = "16"

    /// GET /health and POST /shutdown must not wait on a wedged event loop.
    static let probeTimeoutSeconds: TimeInterval = 2

    static func engineStatus(
        isRunning: Bool,
        isBootstrapping: Bool,
        userStopped: Bool,
        launchError: String?
    ) -> SidecarEngineStatus {
        if isBootstrapping { return .starting }
        if isRunning { return .running }
        if userStopped { return .stopped }
        if launchError != nil { return .failed }
        return .stopped
    }

    static func statusLabel(_ status: SidecarEngineStatus) -> String {
        switch status {
        case .starting: return "正在启动…"
        case .running: return "运行中"
        case .stopped: return "已停止"
        case .failed: return "启动失败"
        }
    }

    static func shouldAutoStart(userStopped: Bool) -> Bool {
        !userStopped
    }

    /// Quit / Settings 停止 must kill whoever holds the port, not only this session's Process.
    static func mustKillPortListenerOnStop(hasOwnedProcess: Bool, portOccupied: Bool) -> Bool {
        hasOwnedProcess || portOccupied
    }

    static func shouldKillListenerBeforeLaunch(
        healthResponded: Bool,
        shouldReplaceOrphan: Bool,
        portOccupied: Bool
    ) -> Bool {
        if healthResponded { return shouldReplaceOrphan }
        return portOccupied
    }

    static func shouldReuseLeftover(healthResponded: Bool, shouldReplaceOrphan: Bool) -> Bool {
        healthResponded && !shouldReplaceOrphan
    }

    static func isCompatible(
        chunkerVersion: String?,
        coreVersion: String?,
        expectedCoreVersion: String
    ) -> Bool {
        !expectedCoreVersion.isEmpty
            && chunkerVersion == expectedChunkerVersion
            && coreVersion == expectedCoreVersion
    }

    /// Whether a process already bound to the sidecar port must be killed before launch.
    ///
    /// Chunker version alone is not enough: ingest/decode fixes ship under the same
    /// `CHUNKER_VERSION`. A leftover frozen binary must yield to this app's version
    /// and to a newer bundled executable (in-place rebuild of the same version).
    static func shouldReplaceOrphan(
        chunkerVersion: String?,
        coreVersion: String?,
        expectedCoreVersion: String,
        hasBundledSidecar: Bool,
        orphanExecutable: String?,
        bundledExecutable: String?,
        orphanStartedAt: Date?,
        bundledModifiedAt: Date?
    ) -> Bool {
        if !isCompatible(
            chunkerVersion: chunkerVersion,
            coreVersion: coreVersion,
            expectedCoreVersion: expectedCoreVersion
        ) {
            return true
        }
        if !hasBundledSidecar {
            return looksLikeFrozenSidecar(orphanExecutable)
        }
        if !pathsReferToSameFile(orphanExecutable, bundledExecutable) {
            return true
        }
        guard let started = orphanStartedAt, let modified = bundledModifiedAt else {
            return true
        }
        return started < modified
    }

    static func looksLikeFrozenSidecar(_ path: String?) -> Bool {
        guard let path, !path.isEmpty else { return false }
        let normalized = path.replacingOccurrences(of: "\\", with: "/")
        return normalized.contains("/Contents/Resources/lumina-core/")
    }

    static func pathsReferToSameFile(_ left: String?, _ right: String?) -> Bool {
        guard let left, let right, !left.isEmpty, !right.isEmpty else { return false }
        return URL(fileURLWithPath: left).standardizedFileURL.path
            == URL(fileURLWithPath: right).standardizedFileURL.path
    }

    /// After polling for bootstrap to begin, should we invoke ensureRunning ourselves?
    static func shouldInvokeEnsureRunning(
        isRunning: Bool,
        isBootstrapping: Bool,
        launchError: String?,
        sawBootstrapStart: Bool
    ) -> Bool {
        if isRunning || isBootstrapping || launchError != nil {
            return false
        }
        return !sawBootstrapStart
    }

    static func isReady(isRunning: Bool, launchError: String?) -> Bool {
        isRunning && launchError == nil
    }
}
