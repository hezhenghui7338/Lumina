namespace Lumina.Services;

public sealed class SidecarHealth
{
    public string Status { get; set; } = "";
    public int? Pid { get; set; }
    public string? ChunkerVersion { get; set; }
    public string? CoreVersion { get; set; }
    public string? Executable { get; set; }
    public long? StartedAt { get; set; }
    public int? UptimeMs { get; set; }
}

public enum HealthPollDecision
{
    Ready,
    KeepWaiting,
    /// `/health` answered but chunker/core identity does not match this app.
    Incompatible,
    /// Owned process exited before becoming healthy.
    ProcessExited,
}

/// Decisions for replacing a leftover lumina-core process on the fixed sidecar port.
public static class SidecarReadiness
{
    public const string ExpectedChunkerVersion = "16";
    public const double HealthPollBudgetSeconds = 30;
    public const string MessageTimeout = "AI 引擎启动超时，请重试或退出。";
    public const string MessageProcessExited = "AI 引擎进程已退出，请重试。";
    public const string MessageIncompatible = "AI 引擎版本与应用不匹配，请更新应用或重启引擎。";

    public static string NormalizeVersion(string? version)
    {
        if (string.IsNullOrWhiteSpace(version)) return "";
        var parts = version.Split('.');
        return parts.Length >= 3 ? string.Join(".", parts[0], parts[1], parts[2]) : version;
    }

    public static bool IsCompatible(string? chunkerVersion, string? coreVersion, string expectedCoreVersion)
    {
        return !string.IsNullOrEmpty(expectedCoreVersion)
            && chunkerVersion == ExpectedChunkerVersion
            && NormalizeVersion(coreVersion) == NormalizeVersion(expectedCoreVersion);
    }

    /// Decide whether to keep polling, succeed, or fail-fast for this launch attempt.
    /// A responding but incompatible health must not burn the full 30s poll budget.
    public static HealthPollDecision EvaluateHealthPoll(
        bool healthResponded,
        bool compatible,
        bool? processStillRunning)
    {
        if (healthResponded)
            return compatible ? HealthPollDecision.Ready : HealthPollDecision.Incompatible;
        if (processStillRunning == false)
            return HealthPollDecision.ProcessExited;
        return HealthPollDecision.KeepWaiting;
    }

    /// Delay after probe `afterProbeIndex` (0 = first probe was immediate).
    public static int HealthPollDelayMilliseconds(int afterProbeIndex)
    {
        if (afterProbeIndex < 20) return 50;
        if (afterProbeIndex < 40) return 100;
        return 250;
    }

    public static string LaunchFailureMessage(HealthPollDecision decision) => decision switch
    {
        HealthPollDecision.Incompatible => MessageIncompatible,
        HealthPollDecision.ProcessExited => MessageProcessExited,
        _ => MessageTimeout,
    };

    public static string IncompatibleDetailMessage(
        string? chunkerVersion,
        string? coreVersion,
        string expectedCoreVersion)
    {
        var engine = $"{NormalizeVersion(coreVersion)}/chunker {chunkerVersion ?? "?"}";
        var expected = $"{NormalizeVersion(expectedCoreVersion)}/chunker {ExpectedChunkerVersion}";
        return $"AI 引擎版本与应用不匹配（引擎 {engine}，应用期望 {expected}）。请更新应用或重启引擎。";
    }

    public static bool ShouldReplaceOrphan(
        string? chunkerVersion,
        string? coreVersion,
        string expectedCoreVersion,
        bool hasBundledSidecar,
        string? orphanExecutable,
        string? bundledExecutable,
        DateTimeOffset? orphanStartedAt,
        DateTimeOffset? bundledModifiedAt)
    {
        if (!IsCompatible(chunkerVersion, coreVersion, expectedCoreVersion))
            return true;
        if (!hasBundledSidecar)
            return LooksLikeFrozenSidecar(orphanExecutable);
        if (!PathsReferToSameFile(orphanExecutable, bundledExecutable))
            return true;
        if (orphanStartedAt is not { } started || bundledModifiedAt is not { } modified)
            return true;
        return started < modified;
    }

    public static bool LooksLikeFrozenSidecar(string? path)
    {
        if (string.IsNullOrEmpty(path)) return false;
        var normalized = path.Replace('\\', '/');
        return normalized.Contains("/lumina-core/lumina-core", StringComparison.OrdinalIgnoreCase)
            || normalized.EndsWith("/lumina-core.exe", StringComparison.OrdinalIgnoreCase);
    }

    public static bool PathsReferToSameFile(string? left, string? right)
    {
        if (string.IsNullOrEmpty(left) || string.IsNullOrEmpty(right)) return false;
        return string.Equals(
            Path.GetFullPath(left),
            Path.GetFullPath(right),
            StringComparison.OrdinalIgnoreCase);
    }

    public static SidecarEngineStatus EngineStatus(
        bool isRunning,
        bool isBootstrapping,
        bool userStopped,
        string? launchError)
    {
        if (isBootstrapping) return SidecarEngineStatus.Starting;
        if (isRunning) return SidecarEngineStatus.Running;
        if (userStopped) return SidecarEngineStatus.Stopped;
        if (!string.IsNullOrEmpty(launchError)) return SidecarEngineStatus.Failed;
        return SidecarEngineStatus.Stopped;
    }

    public static string StatusLabel(SidecarEngineStatus status) => status switch
    {
        SidecarEngineStatus.Starting => "正在启动…",
        SidecarEngineStatus.Running => "运行中",
        SidecarEngineStatus.Failed => "启动失败",
        _ => "已停止",
    };

    public static bool ShouldAutoStart(bool userStopped) => !userStopped;

    public static bool MustKillPortListenerOnStop(bool hasOwnedProcess, bool portOccupied) =>
        hasOwnedProcess || portOccupied;

    public static bool ShouldKillListenerBeforeLaunch(
        bool healthResponded,
        bool shouldReplaceOrphan,
        bool portOccupied)
    {
        if (healthResponded) return shouldReplaceOrphan;
        return portOccupied;
    }

    public static bool ShouldReuseLeftover(bool healthResponded, bool shouldReplaceOrphan) =>
        healthResponded && !shouldReplaceOrphan;
}

public enum SidecarEngineStatus
{
    Starting,
    Running,
    Stopped,
    Failed,
}
