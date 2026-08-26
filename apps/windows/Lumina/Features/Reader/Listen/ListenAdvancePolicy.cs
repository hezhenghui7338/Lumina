namespace Lumina.Features.Reader.Listen;

public abstract record ListenAdvanceDecision
{
    public sealed record Play(int Idx) : ListenAdvanceDecision;
    public sealed record Skip(int Idx, string Reason) : ListenAdvanceDecision;
    public sealed record PauseTooManySkips(int Idx) : ListenAdvanceDecision;
    public sealed record Finished : ListenAdvanceDecision;
}

public static class ListenAdvancePolicy
{
    public const int MaxConsecutiveSkips = 3;

    public static ListenAdvanceDecision Decide(
        int idx,
        int segmentCount,
        bool ready,
        string? skipReason,
        int consecutiveSkips,
        int maxSkips = MaxConsecutiveSkips)
    {
        if (idx < 0 || idx >= segmentCount)
            return new ListenAdvanceDecision.Finished();
        if (ready)
            return new ListenAdvanceDecision.Play(idx);
        var reason = skipReason ?? "summary_not_ready";
        var skips = consecutiveSkips + 1;
        if (skips >= maxSkips)
            return new ListenAdvanceDecision.PauseTooManySkips(idx);
        var next = idx + 1;
        if (next >= segmentCount)
            return new ListenAdvanceDecision.Finished();
        return new ListenAdvanceDecision.Skip(next, reason);
    }
}
