using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace Lumina.Features.Shared;

internal static class ImportConflictDialog
{
    public static async Task<ImportConflictChoice> AskAsync(
        XamlRoot? xamlRoot,
        string title,
        int remainingCount)
    {
        if (xamlRoot is null) return ImportConflictChoice.Skip;

        var skipRemaining = ImportConflictPolicy.ShowSkipRemaining(remainingCount);
        var dlg = new ContentDialog
        {
            Title = "书已存在",
            Content = new TextBlock
            {
                Text = ImportConflictPolicy.DialogMessage(title, remainingCount),
                TextWrapping = TextWrapping.Wrap,
            },
            PrimaryButtonText = "覆盖",
            SecondaryButtonText = skipRemaining ? "跳过剩下所有" : "打开已有",
            CloseButtonText = "跳过",
            XamlRoot = xamlRoot,
        };
        var result = await dlg.ShowAsync();
        return ImportConflictPolicy.ChoiceFromDialog(
            resultIsPrimary: result == ContentDialogResult.Primary,
            resultIsSecondary: result == ContentDialogResult.Secondary,
            showSkipRemaining: skipRemaining);
    }
}
