using System.Collections.ObjectModel;
using System.Text.Json;
using Lumina.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace Lumina.Features.Reader;

public sealed partial class ReaderPage : Page
{
    private string _bookId = "";
    private List<SegmentRow> _segments = [];
    private SegmentRow? _selected;
    private bool _showRaw;
    private CancellationTokenSource? _pageCts;
    private CancellationTokenSource? _eventsCts;
    private CancellationTokenSource? _chatCts;
    private CancellationTokenSource? _hydrateCts;
    private readonly ObservableCollection<ChatMessage> _chat = [];
    private readonly Dictionary<int, SegmentRow> _hydrated = [];
    private readonly List<JsonElement> _eventBuffer = [];
    private DispatcherTimer? _flushTimer;
    private int _readyCount;
    private int _totalCount;

    public ReaderPage()
    {
        InitializeComponent();
        ChatList.ItemsSource = _chat;
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        _pageCts = new CancellationTokenSource();
        if (e.Parameter is ReaderNavArgs args)
        {
            _bookId = args.BookId;
            TitleText.Text = args.Title;
            _ = OpenAsync(args);
        }
    }

    protected override void OnNavigatedFrom(NavigationEventArgs e)
    {
        _pageCts?.Cancel();
        _eventsCts?.Cancel();
        _chatCts?.Cancel();
        _hydrateCts?.Cancel();
        _flushTimer?.Stop();
        base.OnNavigatedFrom(e);
    }

    private async Task OpenAsync(ReaderNavArgs args)
    {
        SegmentLoading.IsActive = true;
        BodyText.Text = "加载中…";
        try
        {
            var open = await App.Core.OpenBookAsync(args.BookId, _pageCts!.Token);
            var segments = await App.Core.ListSegmentsAsync(args.BookId, _pageCts.Token);
            _segments = segments.ToList();
            // Drop heavy raw_text from list binding — hydrate on select.
            foreach (var s in _segments)
            {
                s.RawText = null;
            }
            SegmentList.ItemsSource = _segments;
            _totalCount = _segments.Count;
            _readyCount = _segments.Count(s => s.SummaryStatus is "ready" or "done");
            UpdateProgressBanner();

            var idx = Math.Clamp(open.CurrentSegmentIndex, 0, Math.Max(0, _segments.Count - 1));
            if (_segments.Count > 0)
                SegmentList.SelectedIndex = idx;

            StartEvents();
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            BodyText.Text = ex.Message;
        }
        finally
        {
            SegmentLoading.IsActive = false;
        }
    }

    private void StartEvents()
    {
        _eventsCts?.Cancel();
        _flushTimer?.Stop();
        _flushTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(300) };
        _flushTimer.Tick += (_, _) => FlushEvents();
        _flushTimer.Start();

        _eventsCts = App.Core.SubscribeEvents(_bookId, el =>
        {
            lock (_eventBuffer) { _eventBuffer.Add(el); }
        }, _pageCts?.Token ?? default);
    }

    private void FlushEvents()
    {
        List<JsonElement> batch;
        lock (_eventBuffer)
        {
            if (_eventBuffer.Count == 0) return;
            batch = _eventBuffer.ToList();
            _eventBuffer.Clear();
        }

        foreach (var el in batch)
        {
            if (!el.TryGetProperty("type", out var typeEl)) continue;
            var type = typeEl.GetString();
            if (type is "segment_ready" or "segment_updated")
            {
                if (!el.TryGetProperty("idx", out var idxEl) || !idxEl.TryGetInt32(out var idx))
                    continue;
                var row = _segments.FirstOrDefault(s => s.Idx == idx);
                if (row is null) continue;
                if (el.TryGetProperty("summary_status", out var st))
                    row.SummaryStatus = st.GetString() ?? row.SummaryStatus;
                if (el.TryGetProperty("label", out var lb) && lb.GetString() is { Length: > 0 } label)
                    row.Label = label;
                _hydrated.Remove(idx);
                if (row.SummaryStatus is "ready" or "done")
                    _readyCount = _segments.Count(s => s.SummaryStatus is "ready" or "done");
                if (_selected?.Idx == idx)
                    _ = HydrateSelectedAsync();
            }
            else if (type is "summarize_progress" or "book_updated")
            {
                if (el.TryGetProperty("summary_ready_count", out var rc) && rc.TryGetInt32(out var ready))
                    _readyCount = ready;
                if (el.TryGetProperty("summary_total_count", out var tc) && tc.TryGetInt32(out var total))
                    _totalCount = total;
            }
        }

        var selectedIdx = _selected?.Idx;
        // Refresh list labels without rebuilding entire source when possible.
        SegmentList.ItemsSource = null;
        SegmentList.ItemsSource = _segments;
        if (selectedIdx is int keep)
        {
            var listIdx = _segments.FindIndex(s => s.Idx == keep);
            if (listIdx >= 0) SegmentList.SelectedIndex = listIdx;
        }
        UpdateProgressBanner();
    }

    private void UpdateProgressBanner()
    {
        if (_totalCount <= 0)
        {
            ProgressBanner.Visibility = Visibility.Collapsed;
            return;
        }
        ProgressBanner.Visibility = Visibility.Visible;
        ProgressText.Text = $"摘要进度 {_readyCount}/{_totalCount}";
    }

    private async void SegmentList_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (SegmentList.SelectedItem is not SegmentRow row) return;
        _selected = row;
        await HydrateSelectedAsync();
        try
        {
            _ = App.Core.SaveReadingProgressAsync(_bookId, row.Idx);
        }
        catch { /* non-blocking */ }
    }

    private async Task HydrateSelectedAsync()
    {
        if (_selected is null) return;
        var idx = _selected.Idx;
        _hydrateCts?.Cancel();
        _hydrateCts = CancellationTokenSource.CreateLinkedTokenSource(_pageCts?.Token ?? default);
        var ct = _hydrateCts.Token;

        SegmentLoading.IsActive = true;
        SegmentTitle.Text = _selected.DisplayLabel;
        try
        {
            SegmentRow detail;
            if (_hydrated.TryGetValue(idx, out var cached) &&
                (!_showRaw || !string.IsNullOrEmpty(cached.RawText)))
            {
                detail = cached;
            }
            else
            {
                detail = await App.Core.GetSegmentAsync(_bookId, idx, ct);
                if (string.IsNullOrEmpty(detail.SummaryJson) && detail.SummaryStatus is "ready" or "done")
                {
                    var sum = await App.Core.FetchSegmentSummaryAsync(_bookId, idx, ct);
                    detail.SummaryJson = sum.SummaryJson;
                    if (!string.IsNullOrEmpty(sum.Label)) detail.Label = sum.Label;
                }
                _hydrated[idx] = detail;
            }

            ct.ThrowIfCancellationRequested();
            SegmentTitle.Text = detail.DisplayLabel;
            if (_showRaw)
            {
                var raw = detail.RawText ?? "";
                var translation = string.IsNullOrWhiteSpace(detail.Translation)
                    ? ""
                    : $"\n\n—— 译文 ——\n{detail.Translation}";
                BodyText.Text = string.IsNullOrEmpty(raw) ? "（原文尚未加载）" : raw + translation;
            }
            else
            {
                BodyText.Text = FormatSummary(detail.SummaryJson) ??
                                (detail.SummaryStatus is "ready" or "done"
                                    ? "（摘要为空）"
                                    : $"摘要状态：{detail.SummaryStatus}。可点击「开始摘要」。");
            }
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            BodyText.Text = ex.Message;
        }
        finally
        {
            SegmentLoading.IsActive = false;
        }
    }

    private static string? FormatSummary(string? summaryJson)
    {
        if (string.IsNullOrWhiteSpace(summaryJson)) return null;
        try
        {
            using var doc = JsonDocument.Parse(summaryJson);
            var root = doc.RootElement;
            if (root.ValueKind == JsonValueKind.String)
                return root.GetString();
            if (root.TryGetProperty("summary", out var s))
                return s.GetString();
            if (root.TryGetProperty("text", out var t))
                return t.GetString();
            if (root.TryGetProperty("bullets", out var bullets) && bullets.ValueKind == JsonValueKind.Array)
            {
                var lines = bullets.EnumerateArray()
                    .Select(b => b.GetString())
                    .Where(x => !string.IsNullOrWhiteSpace(x))
                    .Select(x => "• " + x);
                return string.Join("\n", lines);
            }
            return summaryJson;
        }
        catch
        {
            return summaryJson;
        }
    }

    private async void ShowRaw_Click(object sender, RoutedEventArgs e)
    {
        _showRaw = ShowRawToggle.IsChecked == true;
        await HydrateSelectedAsync();
    }

    private async void Summarize_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            await App.Core.StartSummarizeAsync(_bookId);
            ProgressText.Text = "摘要已开始…";
            ProgressBanner.Visibility = Visibility.Visible;
        }
        catch (Exception ex)
        {
            ProgressText.Text = ex.Message;
            ProgressBanner.Visibility = Visibility.Visible;
        }
    }

    private async void StopSummarize_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            await App.Core.StopSummarizeAsync(_bookId);
            ProgressText.Text = "已请求停止摘要";
        }
        catch (Exception ex)
        {
            ProgressText.Text = ex.Message;
        }
    }

    private void OpenChat_Click(object sender, RoutedEventArgs e)
    {
        ChatPanel.Visibility = Visibility.Visible;
        ChatInput.Focus(FocusState.Programmatic);
    }

    private void CloseChat_Click(object sender, RoutedEventArgs e)
    {
        _chatCts?.Cancel();
        ChatPanel.Visibility = Visibility.Collapsed;
    }

    private async void SendChat_Click(object sender, RoutedEventArgs e)
    {
        var message = ChatInput.Text?.Trim();
        if (string.IsNullOrEmpty(message) || _selected is null) return;

        ChatInput.Text = "";
        _chat.Add(new ChatMessage { Role = "你", Content = message });
        var assistant = new ChatMessage { Role = "Lumina", Content = "" };
        _chat.Add(assistant);

        _chatCts?.Cancel();
        _chatCts = CancellationTokenSource.CreateLinkedTokenSource(_pageCts?.Token ?? default);
        var ct = _chatCts.Token;
        var idx = _selected.Idx;

        try
        {
            var resp = await App.Core.ChatStreamAsync(
                _bookId,
                message,
                idx,
                token =>
                {
                    DispatcherQueue.TryEnqueue(() =>
                    {
                        assistant.Content += token;
                        ChatList.ItemsSource = null;
                        ChatList.ItemsSource = _chat;
                    });
                },
                ct: ct);

            assistant.Content = string.IsNullOrEmpty(resp.Answer) ? assistant.Content : resp.Answer;
            assistant.Citations = resp.Citations;
            if (resp.Citations.Count > 0)
            {
                assistant.Content += "\n\n引用：" + string.Join(
                    " ",
                    resp.Citations.Select(c => $"[段 {c.SegmentIndex + 1}]"));
                // Jump to first citation segment (P0: primary evidence).
                var jump = resp.Citations[0].SegmentIndex;
                var listIdx = _segments.FindIndex(s => s.Idx == jump);
                if (listIdx >= 0)
                    SegmentList.SelectedIndex = listIdx;
            }
            ChatList.ItemsSource = null;
            ChatList.ItemsSource = _chat;
        }
        catch (OperationCanceledException)
        {
            assistant.Content += "\n（已取消）";
        }
        catch (Exception ex)
        {
            assistant.Content = ex.Message;
            ChatList.ItemsSource = null;
            ChatList.ItemsSource = _chat;
        }
    }

    private void Back_Click(object sender, RoutedEventArgs e)
    {
        _pageCts?.Cancel();
        MainWindowLocator.Current?.NavigateToLibrary();
    }
}
