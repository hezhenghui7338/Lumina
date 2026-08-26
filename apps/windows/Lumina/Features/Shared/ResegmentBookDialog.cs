using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Lumina.Services;

namespace Lumina.Features.Shared;

internal static class ResegmentBookDialog
{
    public readonly record struct Result(int ChunkTargetChars, SegmentTier Tier);

    public static async Task<Result?> ShowAsync(XamlRoot? xamlRoot, BookSummary book)
    {
        if (xamlRoot is null || !book.CanResegment) return null;

        var target = ResegmentTarget.Normalized(
            book.ChunkTargetChars, book.TotalCharCount, book.SegmentCount ?? 0);
        var box = ChunkTargetField.MakeBox(
            "目标大小（字）", ResegmentTarget.MinChars, ResegmentTarget.MaxChars, target);
        var panel = new StackPanel { Spacing = 8 };
        panel.Children.Add(new TextBlock
        {
            Text = "设置每段的目标字数。实际段落会根据章节和语义边界略有调整。",
            TextWrapping = TextWrapping.Wrap,
        });
        panel.Children.Add(box);
        panel.Children.Add(ChunkTargetField.MakePresetRow(
            box, ResegmentTarget.MinChars, ResegmentTarget.MaxChars));
        var tierBox = new ComboBox { Header = "分段档位", Width = 240 };
        tierBox.Items.Add(new ComboBoxItem { Content = "正常分段", Tag = "normal" });
        tierBox.Items.Add(new ComboBoxItem { Content = "高级分段", Tag = "advanced" });
        tierBox.SelectedIndex = 0;
        panel.Children.Add(tierBox);
        panel.Children.Add(new TextBlock
        {
            Text = "高级分段会额外调用模型校准超长或无标点块。",
            TextWrapping = TextWrapping.Wrap,
        });
        panel.Children.Add(new TextBlock
        {
            Text = "重新分段会删除已有摘要、笔记和本书对话记录，且无法撤销。原始书籍文件不会被修改。",
            TextWrapping = TextWrapping.Wrap,
            Foreground = new Microsoft.UI.Xaml.Media.SolidColorBrush(
                Windows.UI.Color.FromArgb(255, 196, 110, 24)),
        });
        var dlg = new ContentDialog
        {
            Title = $"整书重新分段 · {book.Title}",
            Content = panel,
            PrimaryButtonText = "开始重新分段",
            CloseButtonText = "取消",
            XamlRoot = xamlRoot,
            DefaultButton = ContentDialogButton.Close,
        };
        if (await dlg.ShowAsync() != ContentDialogResult.Primary) return null;

        var chars = ChunkTargetField.ReadClamped(
            box, target, ResegmentTarget.MinChars, ResegmentTarget.MaxChars);
        var tierTag = (tierBox.SelectedItem as ComboBoxItem)?.Tag as string;
        var segmentTier = tierTag == "advanced" ? SegmentTier.Advanced : SegmentTier.Normal;
        if (segmentTier == SegmentTier.Advanced)
        {
            var confirm = new ContentDialog
            {
                Title = "使用高级分段？",
                Content = "高级分段会额外调用模型寻找切点，并删除已有摘要、笔记和本书对话记录。",
                PrimaryButtonText = "确认高级分段",
                CloseButtonText = "取消",
                XamlRoot = xamlRoot,
                DefaultButton = ContentDialogButton.Close,
            };
            if (await confirm.ShowAsync() != ContentDialogResult.Primary) return null;
        }
        return new Result(chars, segmentTier);
    }
}
