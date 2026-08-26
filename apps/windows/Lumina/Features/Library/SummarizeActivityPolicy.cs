using Lumina.Services;

namespace Lumina.Features.Library;

/// Compact library-wide summarize chip copy. Matches macOS SummarizeActivityChip.
public static class SummarizeActivityPolicy
{
    public static string DestinationCollection => LibraryCollections.Summarizing;

    public static bool ShouldShow(int activeCount) => activeCount > 0;

    public static bool ShouldShow(SummarizeOverview overview) =>
        ShouldShow(overview.ActiveCount);

    public static string StatusLabel(
        int running,
        int queued,
        int indexing = 0,
        string? stalledReason = null)
    {
        var parts = new List<string>();
        if (running > 0) parts.Add($"{running} 进行中");
        if (queued > 0) parts.Add($"{queued} 排队");
        if (indexing > 0) parts.Add($"{indexing} 建索引");
        if (running == 0 && queued > 0)
        {
            var reason = SummarizeOverview.StalledLabel(stalledReason);
            if (reason is not null) parts.Add(reason);
        }
        if (parts.Count == 0) parts.Add($"{running} 进行中");
        return string.Join(" · ", parts);
    }

    public static string StatusLabel(SummarizeOverview overview) =>
        StatusLabel(
            overview.Counts.Running,
            overview.Counts.Queued,
            overview.Counts.Indexing,
            overview.StalledReason);
}
