import Foundation

enum SidecarEngineStatus: Equatable {
    case starting
    case running
    case stopped
    case failed
}

/// Outcome of one health probe while waiting for a freshly spawned sidecar.
enum HealthPollDecision: Equatable {
    case ready
    case keepWaiting
    /// `/health` answered but chunker/core identity does not match this app.
    case incompatible
    /// Owned process exited before becoming healthy.
    case processExited
}

/// Pure readiness decisions for SidecarManager (unit-testable).
enum SidecarReadiness {
    /// Must match lumina-core `CHUNKER_VERSION`. A mismatch never marks the sidecar ready,
    /// so library / news / settings all refuse to load.
    static let expectedChunkerVersion = "16"

    /// GET /health and POST /shutdown must not wait on a wedged event loop.
    static let probeTimeoutSeconds: TimeInterval = 2

    /// Extreme upper bound for one launch attempt's health polling (~30s of delays).
    static let healthPollBudgetSeconds: TimeInterval = 30

    static let messageTimeout = "AI 引擎启动超时，请重试或退出。"
    static let messageProcessExited = "AI 引擎进程已退出，请重试。"
    static let messageIncompatible =
        "AI 引擎版本与应用不匹配，请更新应用或重启引擎。"

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

    /// Align with Windows: `1.1.0.0` and `1.1.0` are the same marketing version.
    static func normalizeVersion(_ version: String?) -> String {
        guard let version, !version.isEmpty else { return "" }
        let parts = version.split(separator: ".")
        if parts.count >= 3 {
            return "\(parts[0]).\(parts[1]).\(parts[2])"
        }
        return version
    }

    static func isCompatible(
        chunkerVersion: String?,
        coreVersion: String?,
        expectedCoreVersion: String
    ) -> Bool {
        !expectedCoreVersion.isEmpty
            && chunkerVersion == expectedChunkerVersion
            && normalizeVersion(coreVersion) == normalizeVersion(expectedCoreVersion)
    }

    /// Decide whether to keep polling, succeed, or fail-fast for this launch attempt.
    ///
    /// A responding but incompatible health must not burn the full 30s poll budget.
    static func evaluateHealthPoll(
        healthResponded: Bool,
        compatible: Bool,
        processStillRunning: Bool?
    ) -> HealthPollDecision {
        if healthResponded {
            return compatible ? .ready : .incompatible
        }
        if processStillRunning == false {
            return .processExited
        }
        return .keepWaiting
    }

    /// Delay *after* probe `afterProbeIndex` (0 = first probe was immediate).
    /// Fast early probes, then settle at 250ms; total budget remains ~30s.
    static func healthPollDelayNanoseconds(afterProbeIndex: Int) -> UInt64 {
        if afterProbeIndex < 20 { return 50_000_000 }
        if afterProbeIndex < 40 { return 100_000_000 }
        return 250_000_000
    }

    static func launchFailureMessage(for decision: HealthPollDecision) -> String {
        switch decision {
        case .incompatible:
            return messageIncompatible
        case .processExited:
            return messageProcessExited
        case .ready, .keepWaiting:
            return messageTimeout
        }
    }

    static func incompatibleDetailMessage(
        chunkerVersion: String?,
        coreVersion: String?,
        expectedCoreVersion: String
    ) -> String {
        let engine = "\(normalizeVersion(coreVersion))/chunker \(chunkerVersion ?? "?")"
        let expected = "\(normalizeVersion(expectedCoreVersion))/chunker \(expectedChunkerVersion)"
        return "AI 引擎版本与应用不匹配（引擎 \(engine)，应用期望 \(expected)）。请更新应用或重启引擎。"
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
