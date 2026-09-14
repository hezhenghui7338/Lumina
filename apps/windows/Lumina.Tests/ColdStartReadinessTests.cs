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
    public void Detail_reveal_policy()
    {
        Assert.Equal(TimeSpan.FromSeconds(10), ColdStartReadiness.DetailRevealAfter);
        Assert.False(ColdStartReadiness.ShouldRevealTechnicalDetail(TimeSpan.FromSeconds(9.9)));
        Assert.True(ColdStartReadiness.ShouldRevealTechnicalDetail(TimeSpan.FromSeconds(10)));
    }

    [Fact]
    public void TechnicalDetail_derives_from_internal_phase()
    {
        var engine = ColdStartReadiness.Merge(false, "pending", "pending", "pending", null);
        Assert.Equal("正在启动引擎", ColdStartReadiness.TechnicalDetail(engine));

        var data = ColdStartReadiness.Merge(true, "running", "pending", "pending", null);
        Assert.Equal("正在准备阅读数据", ColdStartReadiness.TechnicalDetail(data));

        var cache = ColdStartReadiness.Merge(
            true, "done", "running", "pending", null, 0.45, "恢复书籍状态 (12/48)");
        Assert.Equal("恢复书籍状态 (12/48)", ColdStartReadiness.TechnicalDetail(cache));

        var cachePlain = ColdStartReadiness.Merge(true, "done", "running", "pending", null);
        Assert.Equal("正在加载缓存", ColdStartReadiness.TechnicalDetail(cachePlain));

        Assert.Equal(
            "无法连接",
            ColdStartReadiness.TechnicalDetail(cachePlain, "无法连接"));
    }
}
