using Lumina.Services;
using Xunit;

namespace Lumina.Tests;

public class ColdStartReadinessTests
{
    [Fact]
    public void IsProductReady_requires_terminal_news()
    {
        var snap = ColdStartReadiness.Merge(true, "done", "done", "running", null);
        Assert.False(ColdStartReadiness.IsProductReady(snap));
        snap = ColdStartReadiness.Merge(true, "done", "done", "done", null);
        Assert.True(ColdStartReadiness.IsProductReady(snap));
        snap = ColdStartReadiness.Merge(true, "done", "done", "failed", "timeout");
        Assert.True(ColdStartReadiness.IsProductReady(snap));
    }

    [Fact]
    public void NewsFailed_label()
    {
        Assert.Equal(
            "更新完毕（未全部成功）",
            ColdStartReadiness.RowLabel("news", ColdStartPhaseState.Failed, true));
    }
}
