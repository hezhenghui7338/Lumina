using Lumina.Services;

namespace Lumina.Features.Reader;

/// Deep-chat citations jump only when the user clicks. Auto-jumping the first
/// citation would yank a single-segment Windows reader off the current page.
public static class ChatCitationJumpPolicy
{
    public static bool AutoJumpOnComplete => false;

    public static string ButtonLabel(int segmentIndex, string? label) =>
        string.IsNullOrWhiteSpace(label)
            ? $"[段 {segmentIndex + 1}]"
            : $"[段 {segmentIndex + 1} · {label}]";

    public static string ButtonLabel(ChatCitation citation) =>
        ButtonLabel(citation.SegmentIndex, citation.Label);

    public static int? TargetIdx(int segmentIndex) =>
        segmentIndex >= 0 ? segmentIndex : null;
}
