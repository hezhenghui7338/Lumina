using Lumina.Services;
using Xunit;

namespace Lumina.Tests;

public class ColdStartReadinessTests
{
    [Fact]
    public void IsProductReady_ignores_news()
    {
        var snap = ColdStartReadiness.Merge(true, "done", "done", "running", null);
        Assert.True(ColdStartReadiness.IsProductReady(snap));
        snap = ColdStartReadiness.Merge(true, "done", "running", "pending", null);
        Assert.False(ColdStartReadiness.IsProductReady(snap));
        snap = ColdStartReadiness.Merge(true, "done", "done", "failed", "timeout");
        Assert.True(ColdStartReadiness.IsProductReady(snap));
        Assert.True(ColdStartReadiness.IsBootNewsTerminal(ColdStartPhaseState.Failed));
        Assert.False(ColdStartReadiness.IsBootNewsTerminal(ColdStartPhaseState.Running));
    }

    [Fact]
    public void Gate_rows_exclude_news()
    {
        Assert.Equal(new[] { "engine", "data", "cache" }, ColdStartReadiness.GateRowKinds);
    }

    [Fact]
    public void CacheProgress_and_detail_in_merge_and_row_label()
    {
        var snap = ColdStartReadiness.Merge(
            true, "done", "running", "pending", null, 0.45, "恢复书籍状态 (12/48)");
        Assert.Equal(ColdStartPhaseState.Running, snap.Cache);
        Assert.Equal(0.45, snap.CacheProgress);
        Assert.Equal("恢复书籍状态 (12/48)", snap.CacheDetail);

        var labelWithDetail = ColdStartReadiness.RowLabel(
            "cache", ColdStartPhaseState.Running, snap.CacheDetail);
        Assert.Equal("缓存加载中 · 恢复书籍状态 (12/48)", labelWithDetail);

        var labelWithoutDetail = ColdStartReadiness.RowLabel(
            "cache", ColdStartPhaseState.Running, null);
        Assert.Equal("缓存加载中", labelWithoutDetail);
    }
}
