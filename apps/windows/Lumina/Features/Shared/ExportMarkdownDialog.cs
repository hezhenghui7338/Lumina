using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace Lumina.Features.Shared;

internal static class ExportMarkdownDialog
{
    public readonly record struct Result(bool IncludeNotes, string Mode);

    public static async Task<Result?> ShowAsync(XamlRoot? xamlRoot)
    {
        if (xamlRoot is null) return null;

        var full = new RadioButton
        {
            Content = "完整摘要版（含译文）",
            GroupName = "exportMarkdownMode",
            IsChecked = true,
        };
        var sentences = new RadioButton
        {
            Content = "仅导出总结（各段三句话）",
            GroupName = "exportMarkdownMode",
        };
        var includeNotes = new CheckBox { Content = "包含我的笔记", IsChecked = false };

        void SyncNotes()
        {
            var sentencesOnly = sentences.IsChecked == true;
            includeNotes.IsEnabled = !sentencesOnly;
            if (sentencesOnly) includeNotes.IsChecked = false;
        }

        full.Checked += (_, _) => SyncNotes();
        sentences.Checked += (_, _) => SyncNotes();

        var caption = new TextBlock
        {
            Text = "完整版默认含译文。仅总结不含要点、注意、追问、译文和笔记。",
            TextWrapping = TextWrapping.Wrap,
            Opacity = 0.7,
        };

        var panel = new StackPanel { Spacing = 8 };
        panel.Children.Add(full);
        panel.Children.Add(sentences);
        panel.Children.Add(includeNotes);
        panel.Children.Add(caption);

        var dlg = new ContentDialog
        {
            Title = "导出 Markdown",
            Content = panel,
            PrimaryButtonText = "导出",
            CloseButtonText = "取消",
            XamlRoot = xamlRoot,
        };
        if (await dlg.ShowAsync() != ContentDialogResult.Primary) return null;

        var mode = sentences.IsChecked == true ? ExportMarkdownMode.Sentences : ExportMarkdownMode.Full;
        return new Result(
            IncludeNotes: ExportMarkdownMode.AllowsNotes(mode) && includeNotes.IsChecked == true,
            Mode: mode);
    }
}
