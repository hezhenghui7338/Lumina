using Lumina.Features.Onboarding;
using Xunit;

namespace Lumina.Tests;

public class OnboardingTourPolicyTests
{
    [Fact]
    public void EmptyLibrary_has_four_steps_ending_in_overview()
    {
        Assert.Equal(
            new[]
            {
                OnboardingTourStep.ImportBook,
                OnboardingTourStep.OpenBook,
                OnboardingTourStep.ConfigureApi,
                OnboardingTourStep.ReaderOverview,
            },
            OnboardingTourPolicy.Steps(false));
        Assert.Equal(
            "知道了",
            OnboardingTourPolicy.PrimaryButtonTitle(OnboardingTourStep.ReaderOverview, false));
        Assert.Equal(
            OnboardingTourStep.ReaderOverview,
            OnboardingTourPolicy.Next(OnboardingTourStep.ConfigureApi, false));
        Assert.Null(OnboardingTourPolicy.Next(OnboardingTourStep.ReaderOverview, false));
    }

    [Fact]
    public void LibraryWithBooks_opens_reader_after_api()
    {
        Assert.Equal(7, OnboardingTourPolicy.Steps(true).Count);
        Assert.Equal(
            OnboardingTourStep.Summarize,
            OnboardingTourPolicy.Next(OnboardingTourStep.ConfigureApi, true));
        Assert.Equal(
            OnboardingTourSurface.Reader,
            OnboardingTourPolicy.Surface(OnboardingTourStep.Summarize));
        Assert.Equal(
            "知道了",
            OnboardingTourPolicy.PrimaryButtonTitle(OnboardingTourStep.Notes, true));
        Assert.Null(OnboardingTourPolicy.Next(OnboardingTourStep.Notes, true));
    }

    [Fact]
    public void Resolve_upgrades_overview_when_books_appear()
    {
        Assert.Equal(
            OnboardingTourStep.Summarize,
            OnboardingTourPolicy.Resolve(OnboardingTourStep.ReaderOverview, true));
        Assert.Equal(
            OnboardingTourStep.ReaderOverview,
            OnboardingTourPolicy.Resolve(OnboardingTourStep.Summarize, false));
    }

    [Fact]
    public void FirstLaunch_does_not_block_on_onboarding_page()
    {
        var root = Path.GetFullPath(Path.Combine(
            AppContext.BaseDirectory, "..", "..", "..", "..", "Lumina"));
        var main = File.ReadAllText(Path.Combine(root, "MainWindow.xaml.cs"));
        Assert.DoesNotContain("OnboardingPage", main);
        Assert.Contains("StartTourAsync", main);
        Assert.Contains("OnboardingDone", main);
        Assert.Contains("ShowUsageGuideAfterTourAsync", main);
        Assert.Contains("UsageGuideDialog", main);

        var settingsXaml = File.ReadAllText(
            Path.Combine(root, "Features", "Settings", "SettingsPage.xaml"));
        var settingsCs = File.ReadAllText(
            Path.Combine(root, "Features", "Settings", "SettingsPage.xaml.cs"));
        Assert.DoesNotContain("重新显示引导", settingsXaml);
        Assert.DoesNotContain("重新显示 spotlight", settingsXaml);
        Assert.Contains("使用指南", settingsXaml);
        Assert.Contains("UsageGuideDialog", settingsCs);

        var onboarding = Path.Combine(root, "Features", "Onboarding");
        Assert.True(File.Exists(Path.Combine(onboarding, "UsageGuideCopy.cs")));
        Assert.True(File.Exists(Path.Combine(onboarding, "UsageGuideDialog.cs")));
        Assert.False(File.Exists(Path.Combine(onboarding, "OnboardingPage.xaml")));
    }
}
