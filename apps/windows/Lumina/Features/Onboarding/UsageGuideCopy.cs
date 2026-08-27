namespace Lumina.Features.Onboarding;

public readonly record struct UsageGuideItem(string Title, string Body);

public static class UsageGuideCopy
{
    public const string Title = "使用指南";

    public static readonly IReadOnlyList<UsageGuideItem> Items =
    [
        new("导入", "书库点「导入」，或把文件拖到书架。"),
        new("阅读", "点书进入。顶栏工具常驻（不复刻浮栏）。"),
        new("摘要 / 原文", "工具栏「原文」。默认看摘要，随时回原文。"),
        new("听", "工具栏「听」总结或原文；播放中可换段、倍速。"),
        new("深聊", "工具栏「深聊」；回答里的段号可跳回原文。"),
        new("查找", "书内 Ctrl+F；跨书笔记与摘要 Ctrl+K。"),
        new("开始摘要", "导入默认只分段；打开书后点「开始摘要」。引擎与 Ollama 在「设置」。"),
    ];
}

public static class UsageGuidePresentationPolicy
{
    public static bool ShouldResetOnboardingOnReopen => false;
    public static bool ShouldPresentGuideAfterFirstRun => true;

    public static bool MarksOnboardingComplete(bool reopenOnly) => !reopenOnly;
}
