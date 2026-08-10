using Lumina.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Navigation;
using Windows.System;

namespace Lumina.Features.Search;

public sealed partial class SearchPage : Page
{
    private CancellationTokenSource? _cts;
    private DispatcherTimer? _debounce;

    public SearchPage()
    {
        InitializeComponent();
        _debounce = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(280) };
        _debounce.Tick += async (_, _) =>
        {
            _debounce.Stop();
            await RunSearchAsync();
        };
        QueryBox.TextChanged += (_, _) =>
        {
            _debounce?.Stop();
            _debounce?.Start();
        };
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        QueryBox.Focus(FocusState.Programmatic);
    }

    protected override void OnNavigatedFrom(NavigationEventArgs e)
    {
        _cts?.Cancel();
        _debounce?.Stop();
        base.OnNavigatedFrom(e);
    }

    private void Close_Click(object sender, RoutedEventArgs e) =>
        MainWindowLocator.Current?.NavigateToLibrary();

    private void QueryBox_KeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (e.Key == VirtualKey.Escape)
        {
            Close_Click(sender, e);
            e.Handled = true;
        }
        else if (e.Key == VirtualKey.Enter)
        {
            _debounce?.Stop();
            _ = RunSearchAsync();
            e.Handled = true;
        }
    }

    private async Task RunSearchAsync()
    {
        var q = QueryBox.Text?.Trim() ?? "";
        if (q.Length < 1)
        {
            ResultsList.ItemsSource = null;
            StatusText.Text = "输入关键词开始搜索";
            return;
        }

        _cts?.Cancel();
        _cts = new CancellationTokenSource();
        var ct = _cts.Token;
        StatusText.Text = "搜索中…";
        try
        {
            var hits = await App.Core.SearchAsync(q, ct);
            ct.ThrowIfCancellationRequested();
            var ordered = hits
                .OrderBy(h => h.Kind switch { "book" => 0, "segment" => 1, "note" => 2, _ => 9 })
                .ToList();
            ResultsList.ItemsSource = ordered;
            StatusText.Text = ordered.Count == 0 ? "无结果" : $"共 {ordered.Count} 条";
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            StatusText.Text = ex.Message;
        }
    }

    private void Results_ItemClick(object sender, ItemClickEventArgs e)
    {
        if (e.ClickedItem is not SearchHit hit) return;
        NavigationHub.RequestOpenBook(hit.BookId, hit.Title, hit.SegmentIndex);
    }
}
