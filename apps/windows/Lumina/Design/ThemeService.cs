using Microsoft.UI.Xaml;

namespace Lumina.Design;

public static class ThemeService
{
    public static ElementTheme Current { get; private set; } = ElementTheme.Light;

    public static void Load()
    {
        Current = LocalPrefs.Theme switch
        {
            "Dark" => ElementTheme.Dark,
            _ => ElementTheme.Light,
        };
    }

    public static void Apply(FrameworkElement? root, ElementTheme theme)
    {
        Current = theme;
        if (root is not null)
            root.RequestedTheme = theme;
        LocalPrefs.Theme = theme.ToString();
    }

    public static bool OnboardingDone
    {
        get => LocalPrefs.OnboardingDone;
        set => LocalPrefs.OnboardingDone = value;
    }
}
