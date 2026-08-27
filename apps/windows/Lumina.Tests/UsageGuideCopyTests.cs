using Lumina.Features.Onboarding;
using Xunit;

namespace Lumina.Tests;

public class UsageGuideCopyTests
{
    [Fact]
    public void UsageGuide_has_seven_daily_steps()
    {
        Assert.Equal("使用指南", UsageGuideCopy.Title);
        Assert.Equal(7, UsageGuideCopy.Items.Count);
        Assert.Equal(
            new[] { "导入", "阅读", "摘要 / 原文", "听", "深聊", "查找", "开始摘要" },
            UsageGuideCopy.Items.Select(i => i.Title).ToArray());
    }

    [Fact]
    public void UsageGuide_windows_chrome_mentions_toolbar_not_blank_click()
    {
        var bodies = string.Join("\n", UsageGuideCopy.Items.Select(i => i.Body));
        Assert.Contains("顶栏工具常驻", bodies);
        Assert.Contains("Ctrl+F", bodies);
        Assert.Contains("Ctrl+K", bodies);
        Assert.DoesNotContain("点空白", bodies);
    }

    [Fact]
    public void Reopening_guide_does_not_reset_onboarding()
    {
        Assert.False(UsageGuidePresentationPolicy.ShouldResetOnboardingOnReopen);
        Assert.True(UsageGuidePresentationPolicy.ShouldPresentGuideAfterFirstRun);
        Assert.True(UsageGuidePresentationPolicy.MarksOnboardingComplete(reopenOnly: false));
        Assert.False(UsageGuidePresentationPolicy.MarksOnboardingComplete(reopenOnly: true));
    }

    [Fact]
    public void Settings_reopens_guide_without_resetting_onboarding()
    {
        var root = Path.GetFullPath(Path.Combine(
            AppContext.BaseDirectory, "..", "..", "..", "..", "Lumina"));
        var settingsXaml = File.ReadAllText(
            Path.Combine(root, "Features", "Settings", "SettingsPage.xaml"));
        var settingsCs = File.ReadAllText(
            Path.Combine(root, "Features", "Settings", "SettingsPage.xaml.cs"));
        var main = File.ReadAllText(Path.Combine(root, "MainWindow.xaml.cs"));
        Assert.Contains("使用指南", settingsXaml);
        Assert.Contains("UsageGuideDialog", settingsCs);
        Assert.DoesNotContain("OnboardingDone = false", settingsCs);
        Assert.Contains("ShouldPresentGuideAfterFirstRun", main);
        Assert.DoesNotContain("OnboardingDone = false", main);
        Assert.DoesNotContain("OnboardingPage", main);
    }
}
