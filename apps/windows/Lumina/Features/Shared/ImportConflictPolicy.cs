namespace Lumina.Features.Shared;

public enum ImportConflictChoice
{
    Overwrite,
    Skip,
    SkipRemainingDuplicates,
    OpenExisting,
    CancelRemaining,
}

public readonly record struct ImportConflictDecision(
    bool OverwriteCurrent,
    bool SkipRemainingDuplicates,
    bool ContinueQueue,
    bool OpenExisting);

public static class ImportConflictPolicy
{
    public static bool ShouldPrompt(bool skipRemainingDuplicates) => !skipRemainingDuplicates;

    public static bool ShowSkipRemaining(int remainingCount) => remainingCount > 0;

    public static ImportConflictDecision Decide(ImportConflictChoice choice) => choice switch
    {
        ImportConflictChoice.Overwrite => new(true, false, true, false),
        ImportConflictChoice.Skip => new(false, false, true, false),
        ImportConflictChoice.SkipRemainingDuplicates => new(false, true, true, false),
        ImportConflictChoice.OpenExisting => new(false, false, true, true),
        ImportConflictChoice.CancelRemaining => new(false, false, false, false),
        _ => new(false, false, true, false),
    };

    /// Maps a 3-button dialog: Primary = overwrite; Secondary = skip-remaining
    /// (batch) or open-existing (last file); Close = skip this file.
    public static ImportConflictChoice ChoiceFromDialog(
        bool resultIsPrimary,
        bool resultIsSecondary,
        bool showSkipRemaining)
    {
        if (resultIsPrimary) return ImportConflictChoice.Overwrite;
        if (resultIsSecondary)
        {
            return showSkipRemaining
                ? ImportConflictChoice.SkipRemainingDuplicates
                : ImportConflictChoice.OpenExisting;
        }
        return ImportConflictChoice.Skip;
    }

    public static string DialogMessage(string title, int remainingCount)
    {
        var body = $"「{title}」已在书库中。覆盖将删除原有摘要、笔记，并重新分段与摘要";
        if (remainingCount <= 0) return body + "。";
        return body + "；跳过会继续导入其他书籍。「跳过剩下所有」会跳过本书及后续重复书，不再询问，但仍导入新书。";
    }
}
