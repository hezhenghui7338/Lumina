using Microsoft.UI.Text;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace Lumina.Features.Onboarding;

internal static class UsageGuideContent
{
    public static UIElement Create()
    {
        var stack = new StackPanel { Spacing = 14 };
        foreach (var item in UsageGuideCopy.Items)
        {
            stack.Children.Add(new TextBlock
            {
                Text = item.Title,
                FontSize = 16,
                FontWeight = FontWeights.SemiBold,
            });
            stack.Children.Add(new TextBlock
            {
                Text = item.Body,
                TextWrapping = TextWrapping.WrapWholeWords,
                Opacity = 0.8,
            });
        }
        return stack;
    }
}

internal static class UsageGuideDialog
{
    public static async Task ShowAsync(XamlRoot? root)
    {
        if (root is null) return;
        var dlg = new ContentDialog
        {
            Title = UsageGuideCopy.Title,
            Content = new ScrollViewer
            {
                Content = UsageGuideContent.Create(),
                MaxHeight = 420,
            },
            CloseButtonText = "好",
            XamlRoot = root,
            DefaultButton = ContentDialogButton.Close,
        };
        await dlg.ShowAsync();
    }
}
