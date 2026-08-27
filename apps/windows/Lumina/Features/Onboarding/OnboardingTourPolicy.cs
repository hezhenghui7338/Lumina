namespace Lumina.Features.Onboarding;

public enum OnboardingTourStep
{
    ImportBook,
    OpenBook,
    ConfigureApi,
    Summarize,
    ToggleMode,
    Chat,
    Notes,
    ReaderOverview,
}

public enum OnboardingTourSurface
{
    Library,
    Settings,
    Reader,
}

public enum OnboardingTourAnchor
{
    ImportButton,
    Bookshelf,
    ApiResources,
    Summarize,
    ModePicker,
    Chat,
    Notes,
}

public readonly record struct OnboardingTourCopy(string Title, string Body);

public static class OnboardingTourPolicy
{
    public static IReadOnlyList<OnboardingTourStep> Steps(bool hasOpenableBook) =>
        hasOpenableBook
            ? [
                OnboardingTourStep.ImportBook,
                OnboardingTourStep.OpenBook,
                OnboardingTourStep.ConfigureApi,
                OnboardingTourStep.Summarize,
                OnboardingTourStep.ToggleMode,
                OnboardingTourStep.Chat,
                OnboardingTourStep.Notes,
            ]
            : [
                OnboardingTourStep.ImportBook,
                OnboardingTourStep.OpenBook,
                OnboardingTourStep.ConfigureApi,
                OnboardingTourStep.ReaderOverview,
            ];

    public static OnboardingTourStep Resolve(OnboardingTourStep step, bool hasOpenableBook)
    {
        var visible = Steps(hasOpenableBook);
        if (visible.Contains(step)) return step;
        return step switch
        {
            OnboardingTourStep.Summarize or OnboardingTourStep.ToggleMode
                or OnboardingTourStep.Chat or OnboardingTourStep.Notes
                or OnboardingTourStep.ReaderOverview =>
                hasOpenableBook ? OnboardingTourStep.Summarize : OnboardingTourStep.ReaderOverview,
            _ => visible[0],
        };
    }

    public static OnboardingTourStep? Next(OnboardingTourStep step, bool hasOpenableBook)
    {
        var visible = Steps(hasOpenableBook);
        var current = Resolve(step, hasOpenableBook);
        var idx = IndexOf(visible, current);
        if (idx < 0) return visible.Count > 0 ? visible[0] : null;
        return idx + 1 < visible.Count ? visible[idx + 1] : null;
    }

    public static OnboardingTourStep? Previous(OnboardingTourStep step, bool hasOpenableBook)
    {
        var visible = Steps(hasOpenableBook);
        var current = Resolve(step, hasOpenableBook);
        var idx = IndexOf(visible, current);
        return idx > 0 ? visible[idx - 1] : null;
    }

    public static OnboardingTourSurface Surface(OnboardingTourStep step) => step switch
    {
        OnboardingTourStep.ImportBook or OnboardingTourStep.OpenBook
            or OnboardingTourStep.ReaderOverview => OnboardingTourSurface.Library,
        OnboardingTourStep.ConfigureApi => OnboardingTourSurface.Settings,
        _ => OnboardingTourSurface.Reader,
    };

    public static OnboardingTourAnchor Anchor(OnboardingTourStep step, bool hasOpenableBook) =>
        step switch
        {
            OnboardingTourStep.ImportBook => hasOpenableBook
                ? OnboardingTourAnchor.Bookshelf
                : OnboardingTourAnchor.ImportButton,
            OnboardingTourStep.OpenBook or OnboardingTourStep.ReaderOverview =>
                OnboardingTourAnchor.Bookshelf,
            OnboardingTourStep.ConfigureApi => OnboardingTourAnchor.ApiResources,
            OnboardingTourStep.Summarize => OnboardingTourAnchor.Summarize,
            OnboardingTourStep.ToggleMode => OnboardingTourAnchor.ModePicker,
            OnboardingTourStep.Chat => OnboardingTourAnchor.Chat,
            OnboardingTourStep.Notes => OnboardingTourAnchor.Notes,
            _ => OnboardingTourAnchor.Bookshelf,
        };

    public static OnboardingTourCopy Copy(OnboardingTourStep step, bool hasOpenableBook) =>
        step switch
        {
            OnboardingTourStep.ImportBook when hasOpenableBook =>
                new("导入书籍", "点右上角导入图标，或把文件拖到书架上。"),
            OnboardingTourStep.ImportBook =>
                new("导入书籍", "点这里或把文件拖到书架，支持 PDF、EPUB、TXT 等。"),
            OnboardingTourStep.OpenBook =>
                new("选择书籍阅读", "点一本书打开阅读器，第一段就绪就能读。"),
            OnboardingTourStep.ConfigureApi =>
                new("配置摘要 API", "在此添加本机 Ollama 或外部 API Key，摘要与深聊都会用到。"),
            OnboardingTourStep.Summarize =>
                new("点击摘要", "点顶栏摘要图标，开始为各段生成摘要。"),
            OnboardingTourStep.ToggleMode =>
                new("切换摘要与原文", "用工具栏「原文」随时对照摘要。"),
            OnboardingTourStep.Chat =>
                new("深聊", "工具栏「深聊」可针对当前段追问。"),
            OnboardingTourStep.Notes =>
                new("笔记", "工具栏「笔记」记下想法，并挂在当前段上。"),
            OnboardingTourStep.ReaderOverview =>
                new("阅读器里还可以", "打开书后：工具栏可点摘要、切换原文；也可深聊和记笔记。"),
            _ => new("", ""),
        };

    public static bool IsFirst(OnboardingTourStep step, bool hasOpenableBook) =>
        Steps(hasOpenableBook)[0] == Resolve(step, hasOpenableBook);

    public static bool IsLast(OnboardingTourStep step, bool hasOpenableBook)
    {
        var visible = Steps(hasOpenableBook);
        return visible[^1] == Resolve(step, hasOpenableBook);
    }

    public static string PrimaryButtonTitle(OnboardingTourStep step, bool hasOpenableBook) =>
        IsLast(step, hasOpenableBook) ? "知道了" : "下一步";

    public static int Index(OnboardingTourStep step, bool hasOpenableBook)
    {
        var visible = Steps(hasOpenableBook);
        var idx = IndexOf(visible, Resolve(step, hasOpenableBook));
        return idx < 0 ? 0 : idx;
    }

    public static int Count(bool hasOpenableBook) => Steps(hasOpenableBook).Count;

    private static int IndexOf(IReadOnlyList<OnboardingTourStep> steps, OnboardingTourStep step)
    {
        for (var i = 0; i < steps.Count; i++)
        {
            if (steps[i] == step) return i;
        }
        return -1;
    }
}
