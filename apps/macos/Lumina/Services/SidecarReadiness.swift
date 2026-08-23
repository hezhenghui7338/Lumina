import Foundation

/// Pure readiness decisions for SidecarManager (unit-testable).
enum SidecarReadiness {
    /// Must match lumina-core `CHUNKER_VERSION`. A mismatch never marks the sidecar ready,
    /// so library / news / settings all refuse to load.
    static let expectedChunkerVersion = "10"

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
