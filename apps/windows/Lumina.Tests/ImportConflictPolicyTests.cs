using Lumina.Features.Shared;
using Xunit;

namespace Lumina.Tests;

public class ImportConflictPolicyTests
{
    [Fact]
    public void SkipRemaining_skips_current_and_keeps_importing_new_books()
    {
        var decision = ImportConflictPolicy.Decide(ImportConflictChoice.SkipRemainingDuplicates);
        Assert.False(decision.OverwriteCurrent);
        Assert.True(decision.SkipRemainingDuplicates);
        Assert.True(decision.ContinueQueue);
        Assert.False(decision.OpenExisting);
    }

    [Fact]
    public void CancelRemaining_stops_queue_including_new_books()
    {
        var decision = ImportConflictPolicy.Decide(ImportConflictChoice.CancelRemaining);
        Assert.False(decision.OverwriteCurrent);
        Assert.False(decision.SkipRemainingDuplicates);
        Assert.False(decision.ContinueQueue);
    }

    [Fact]
    public void SkipOnce_still_prompts_later_conflicts()
    {
        var decision = ImportConflictPolicy.Decide(ImportConflictChoice.Skip);
        Assert.False(decision.SkipRemainingDuplicates);
        Assert.True(decision.ContinueQueue);
        Assert.True(ImportConflictPolicy.ShouldPrompt(false));
        Assert.False(ImportConflictPolicy.ShouldPrompt(true));
    }

    [Fact]
    public void BatchDialog_secondary_is_skip_remaining_not_open_existing()
    {
        Assert.Equal(
            ImportConflictChoice.SkipRemainingDuplicates,
            ImportConflictPolicy.ChoiceFromDialog(
                resultIsPrimary: false, resultIsSecondary: true, showSkipRemaining: true));
        Assert.Equal(
            ImportConflictChoice.OpenExisting,
            ImportConflictPolicy.ChoiceFromDialog(
                resultIsPrimary: false, resultIsSecondary: true, showSkipRemaining: false));
        Assert.Equal(
            ImportConflictChoice.Skip,
            ImportConflictPolicy.ChoiceFromDialog(
                resultIsPrimary: false, resultIsSecondary: false, showSkipRemaining: true));
        Assert.Equal(
            ImportConflictChoice.Overwrite,
            ImportConflictPolicy.ChoiceFromDialog(
                resultIsPrimary: true, resultIsSecondary: false, showSkipRemaining: true));
    }

    [Fact]
    public void ShowSkipRemaining_only_when_queue_has_more_files()
    {
        Assert.False(ImportConflictPolicy.ShowSkipRemaining(0));
        Assert.True(ImportConflictPolicy.ShowSkipRemaining(1));
    }

    [Fact]
    public void DialogMessage_explains_skip_remaining_when_queue_remains()
    {
        var single = ImportConflictPolicy.DialogMessage("旧书", 0);
        Assert.Contains("「旧书」已在书库中", single);
        Assert.DoesNotContain("跳过剩下所有", single);

        var batch = ImportConflictPolicy.DialogMessage("旧书", 3);
        Assert.Contains("跳过剩下所有", batch);
        Assert.Contains("仍导入新书", batch);
    }
}
