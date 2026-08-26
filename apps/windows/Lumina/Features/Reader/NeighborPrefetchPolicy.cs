namespace Lumina.Features.Reader;

/// Prefetch only idx±1 so segment turns stay off the UI thread without loading the book.
public static class NeighborPrefetchPolicy
{
    public static IReadOnlyList<int> Neighbors(int idx, IReadOnlyList<int> sortedIdx)
    {
        if (sortedIdx.Count == 0) return [];
        var pos = -1;
        for (var i = 0; i < sortedIdx.Count; i++)
        {
            if (sortedIdx[i] == idx)
            {
                pos = i;
                break;
            }
        }
        if (pos < 0) return [];
        var result = new List<int>(2);
        if (pos > 0) result.Add(sortedIdx[pos - 1]);
        if (pos + 1 < sortedIdx.Count) result.Add(sortedIdx[pos + 1]);
        return result;
    }

    public static bool NeedsRawText(bool showRaw) => showRaw;

    public static bool NeedsSummaryJson(bool showRaw) => !showRaw;
}
