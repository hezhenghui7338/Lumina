import Foundation

/// Pure readiness decisions for SidecarManager (unit-testable).
enum SidecarReadiness {
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
