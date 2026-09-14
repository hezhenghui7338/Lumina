namespace Lumina.Features.Reader;

/// Prefetch neighbourhood after entering a segment (PRD: current → down 15 → up 5).
public static class NeighborPrefetchPolicy
{
    public const int ForwardCount = 15;
    public const int BackwardCount = 5;

    public static IReadOnlyList<int> Neighbors(int idx, IReadOnlyList<int> sortedIdx)
        => Neighbors(idx, sortedIdx, BackwardCount, ForwardCount);

    public static IReadOnlyList<int> Neighbors(
        int idx,
        IReadOnlyList<int> sortedIdx,
        int back,
        int forward
    )
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
        var start = Math.Max(0, pos - back);
        var end = Math.Min(sortedIdx.Count - 1, pos + forward);
        var result = new List<int>(end - start + 1);
        for (var i = start; i <= end; i++)
        {
            if (i == pos) continue;
            result.Add(sortedIdx[i]);
        }
        return result;
    }

    public static bool NeedsRawText(bool showRaw) => showRaw;

    public static bool NeedsSummaryJson(bool showRaw) => !showRaw;
}
