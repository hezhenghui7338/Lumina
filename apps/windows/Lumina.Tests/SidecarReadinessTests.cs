using Lumina.Services;
using Xunit;

namespace Lumina.Tests;

public class SidecarReadinessTests
{
    [Fact]
    public void IsCompatible_requires_chunker_and_core_version()
    {
        var chunker = SidecarReadiness.ExpectedChunkerVersion;
        Assert.True(SidecarReadiness.IsCompatible(chunker, "0.8.1", "0.8.1"));
        Assert.True(SidecarReadiness.IsCompatible(chunker, "0.8.1.0", "0.8.1"));
        Assert.False(SidecarReadiness.IsCompatible("8", "0.8.1", "0.8.1"));
        Assert.False(SidecarReadiness.IsCompatible(chunker, "0.8.0", "0.8.1"));
        Assert.False(SidecarReadiness.IsCompatible(chunker, null, "0.8.1"));
    }

    [Fact]
    public void ShouldReplaceOrphan_when_core_version_differs()
    {
        Assert.True(Replace(
            core: "0.8.0",
            expected: "0.8.1",
            bundled: true,
            orphanExe: @"C:\Lumina\lumina-core\lumina-core.exe",
            bundledExe: @"C:\Lumina\lumina-core\lumina-core.exe",
            started: Unix(200),
            modified: Unix(100)));
    }

    [Fact]
    public void ShouldReplaceOrphan_when_bundled_binary_is_newer()
    {
        Assert.True(Replace(
            core: "0.8.1",
            expected: "0.8.1",
            bundled: true,
            orphanExe: @"C:\Lumina\lumina-core\lumina-core.exe",
            bundledExe: @"C:\Lumina\lumina-core\lumina-core.exe",
            started: Unix(100),
            modified: Unix(200)));
    }

    [Fact]
    public void ShouldReplaceOrphan_keeps_same_build()
    {
        Assert.False(Replace(
            core: "0.8.1",
            expected: "0.8.1",
            bundled: true,
            orphanExe: @"C:\Lumina\lumina-core\lumina-core.exe",
            bundledExe: @"C:\Lumina\lumina-core\lumina-core.exe",
            started: Unix(200),
            modified: Unix(100)));
    }

    [Fact]
    public void ShouldReplaceOrphan_legacy_health_without_core_version()
    {
        Assert.True(Replace(
            core: null,
            expected: "0.8.1",
            bundled: true,
            orphanExe: @"C:\Lumina\lumina-core\lumina-core.exe",
            bundledExe: @"C:\Lumina\lumina-core\lumina-core.exe",
            started: Unix(200),
            modified: Unix(100)));
    }

    [Fact]
    public void ShouldAutoStart_false_when_user_stopped()
    {
        Assert.False(SidecarReadiness.ShouldAutoStart(true));
        Assert.True(SidecarReadiness.ShouldAutoStart(false));
    }

    [Fact]
    public void MustKillPortListenerOnStop_even_without_owned_process()
    {
        Assert.True(SidecarReadiness.MustKillPortListenerOnStop(false, true));
        Assert.True(SidecarReadiness.MustKillPortListenerOnStop(true, false));
        Assert.False(SidecarReadiness.MustKillPortListenerOnStop(false, false));
    }

    [Fact]
    public void ShouldKillListenerBeforeLaunch_when_health_times_out_and_port_occupied()
    {
        Assert.True(SidecarReadiness.ShouldKillListenerBeforeLaunch(false, false, true));
        Assert.False(SidecarReadiness.ShouldKillListenerBeforeLaunch(false, false, false));
        Assert.False(SidecarReadiness.ShouldReuseLeftover(false, false));
    }

    [Fact]
    public void EngineStatus_user_stopped_is_stopped_not_failed()
    {
        Assert.Equal(
            SidecarEngineStatus.Stopped,
            SidecarReadiness.EngineStatus(false, false, true, null));
        Assert.Equal("运行中", SidecarReadiness.StatusLabel(SidecarEngineStatus.Running));
    }

    private static DateTimeOffset Unix(long seconds) => DateTimeOffset.FromUnixTimeSeconds(seconds);

    private static bool Replace(
        string? core,
        string expected,
        bool bundled,
        string? orphanExe,
        string? bundledExe,
        DateTimeOffset? started,
        DateTimeOffset? modified) =>
        SidecarReadiness.ShouldReplaceOrphan(
            SidecarReadiness.ExpectedChunkerVersion,
            core,
            expected,
            bundled,
            orphanExe,
            bundledExe,
            started,
            modified);
}
