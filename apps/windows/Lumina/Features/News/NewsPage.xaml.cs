using System.Collections.ObjectModel;
using Lumina.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;
using Windows.System;

namespace Lumina.Features.News;

public sealed partial class NewsPage : Page
{
    private CancellationTokenSource? _cts;
    private CancellationTokenSource? _chatCts;
    private List<NewsArticleCard> _articles = [];
    private List<NewsSource> _sources = [];
    private NewsArticleCard? _selected;
    private readonly ObservableCollection<string> _chatLines = [];

    public NewsPage()
    {
        InitializeComponent();
        ChatList.ItemsSource = _chatLines;
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        _ = LoadBriefAsync();
    }

    protected override void OnNavigatedFrom(NavigationEventArgs e)
    {
        _cts?.Cancel();
        _chatCts?.Cancel();
        base.OnNavigatedFrom(e);
    }

    private async Task LoadBriefAsync()
    {
        _cts?.Cancel();
        _cts = new CancellationTokenSource();
        var ct = _cts.Token;
        StatusText.Text = "加载简报…";
        try
        {
            var sourcesTask = App.Core.FetchNewsSourcesAsync(ct);
            var briefTask = App.Core.FetchNewsBriefAsync(40, ct);
            await Task.WhenAll(sourcesTask, briefTask);
            _sources = sourcesTask.Result.ToList();
            _articles = briefTask.Result.Articles.ToList();

            SourceFilterBox.Items.Clear();
            SourceFilterBox.Items.Add(new ComboBoxItem { Content = "全部信源", Tag = "", IsSelected = true });
            foreach (var s in _sources)
                SourceFilterBox.Items.Add(new ComboBoxItem { Content = s.DisplayTitle, Tag = s.Id });

            ApplyFilter();
            StatusText.Text = $"{briefTask.Result.Date} · {briefTask.Result.Count} 篇";
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            StatusText.Text = ex.Message;
        }
    }

    private void ApplyFilter()
    {
        var sid = (SourceFilterBox.SelectedItem as ComboBoxItem)?.Tag as string ?? "";
        var list = string.IsNullOrEmpty(sid)
            ? _articles
            : _articles.Where(a => a.SourceId == sid).ToList();
        ArticlesList.ItemsSource = list;
    }

    private void SourceFilter_Changed(object sender, SelectionChangedEventArgs e) => ApplyFilter();

    private void Articles_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (ArticlesList.SelectedItem is not NewsArticleCard card) return;
        _selected = card;
        ArticleTitle.Text = card.Title;
        ArticleMeta.Text = $"{card.DisplaySource} · {card.PublishedAt}";
        SummaryText.Text = card.Detail ?? card.OneLiner ?? card.Excerpt ?? "点击「精读」生成摘要";
        BodyText.Text = "";
        if (Uri.TryCreate(card.Url, UriKind.Absolute, out var u))
            OpenUrlBtn.NavigateUri = u;
    }

    private async void Sync_Click(object sender, RoutedEventArgs e)
    {
        StatusText.Text = "同步中…（可继续浏览）";
        try
        {
            var results = await App.Core.SyncNewsAsync();
            var added = results.Sum(r => r.Added ?? 0);
            StatusText.Text = $"同步完成 · 新增约 {added}";
            await LoadBriefAsync();
        }
        catch (Exception ex)
        {
            StatusText.Text = ex.Message;
        }
    }

    private async void Sources_Click(object sender, RoutedEventArgs e)
    {
        var panel = new StackPanel { Spacing = 8 };
        var list = new TextBlock { TextWrapping = TextWrapping.WrapWholeWords };
        void RefreshList()
        {
            list.Text = _sources.Count == 0
                ? "暂无信源"
                : string.Join("\n", _sources.Select(s => $"• [{s.Id}] {s.DisplayTitle}"));
        }
        RefreshList();
        var urlBox = new TextBox { PlaceholderText = "https://…" };
        var titleBox = new TextBox { PlaceholderText = "标题（可选）" };
        panel.Children.Add(list);
        panel.Children.Add(urlBox);
        panel.Children.Add(titleBox);

        var deleteIdBox = new TextBox { PlaceholderText = "删除：粘贴信源 id（可选）" };
        panel.Children.Add(deleteIdBox);

        var dlg = new ContentDialog
        {
            Title = "管理信源",
            Content = panel,
            PrimaryButtonText = "添加",
            SecondaryButtonText = "恢复默认",
            CloseButtonText = "关闭",
            XamlRoot = XamlRoot,
        };
        var result = await dlg.ShowAsync();
        try
        {
            if (!string.IsNullOrWhiteSpace(deleteIdBox.Text))
            {
                await App.Core.DeleteNewsSourceAsync(deleteIdBox.Text.Trim());
                await LoadBriefAsync();
                return;
            }
            if (result == ContentDialogResult.Primary && !string.IsNullOrWhiteSpace(urlBox.Text))
            {
                await App.Core.AddNewsSourceAsync(urlBox.Text.Trim(), titleBox.Text.Trim());
                await LoadBriefAsync();
            }
            else if (result == ContentDialogResult.Secondary)
            {
                await App.Core.RestoreNewsDefaultsAsync();
                await LoadBriefAsync();
            }
        }
        catch (Exception ex)
        {
            StatusText.Text = ex.Message;
        }
    }

    private async void Read_Click(object sender, RoutedEventArgs e)
    {
        if (_selected is null) return;
        ReadRing.IsActive = true;
        try
        {
            var result = await App.Core.ReadNewsArticleAsync(_selected.Id);
            SummaryText.Text = string.IsNullOrWhiteSpace(result.SummaryMarkdown)
                ? (result.Error.Length > 0 ? result.Error : "（无摘要）")
                : result.SummaryMarkdown;
            BodyText.Text = result.BodyText ?? "";
            if (result.Warnings.Count > 0)
                ArticleMeta.Text += " · " + string.Join("；", result.Warnings);
        }
        catch (Exception ex)
        {
            SummaryText.Text = ex.Message;
        }
        finally
        {
            ReadRing.IsActive = false;
        }
    }

    private async void OpenUrl_Click(object sender, RoutedEventArgs e)
    {
        if (_selected is null || !Uri.TryCreate(_selected.Url, UriKind.Absolute, out var u)) return;
        await Launcher.LaunchUriAsync(u);
    }

    private void ToggleChat_Click(object sender, RoutedEventArgs e)
    {
        ChatPanel.Visibility = ChatPanel.Visibility == Visibility.Visible
            ? Visibility.Collapsed
            : Visibility.Visible;
    }

    private async void SendChat_Click(object sender, RoutedEventArgs e)
    {
        if (_selected is null) return;
        var msg = ChatInput.Text?.Trim();
        if (string.IsNullOrEmpty(msg)) return;
        ChatInput.Text = "";
        _chatLines.Add("你：" + msg);
        var assistantIdx = _chatLines.Count;
        _chatLines.Add("Lumina：");

        _chatCts?.Cancel();
        _chatCts = new CancellationTokenSource();
        try
        {
            var resp = await App.Core.NewsChatStreamAsync(
                _selected.Id,
                msg,
                token =>
                {
                    DispatcherQueue.TryEnqueue(() =>
                    {
                        if (assistantIdx < _chatLines.Count)
                            _chatLines[assistantIdx] += token;
                    });
                },
                ct: _chatCts.Token);
            if (!string.IsNullOrEmpty(resp.Answer))
                _chatLines[assistantIdx] = "Lumina：" + resp.Answer;
        }
        catch (OperationCanceledException)
        {
            _chatLines[assistantIdx] += "（已取消）";
        }
        catch (Exception ex)
        {
            _chatLines[assistantIdx] = "Lumina：" + ex.Message;
        }
    }
}
