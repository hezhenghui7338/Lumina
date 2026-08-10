using System.Collections.ObjectModel;
using System.Text.Json;
using Lumina.Design;
using Lumina.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Navigation;
using Windows.Storage.Pickers;
using Windows.System;
using WinRT.Interop;

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
    private int? _pendingJump;
    private ChatMessage? _lastAssistant;

    public ReaderPage()
    {
        InitializeComponent();
        ChatList.ItemsSource = _chat;
        KeyDown += ReaderPage_KeyDown;
    }

    private void ReaderPage_KeyDown(object sender, KeyRoutedEventArgs e)
    {
        var ctrl = Microsoft.UI.Input.InputKeyboardSource.GetKeyStateForCurrentThread(VirtualKey.Control)
            .HasFlag(Windows.UI.Core.CoreVirtualKeyStates.Down);
        var shift = Microsoft.UI.Input.InputKeyboardSource.GetKeyStateForCurrentThread(VirtualKey.Shift)
            .HasFlag(Windows.UI.Core.CoreVirtualKeyStates.Down);
        if (ctrl && shift && e.Key == VirtualKey.O)
        {
            ShowRawToggle.IsChecked = !(ShowRawToggle.IsChecked ?? false);
            ShowRaw_Click(ShowRawToggle, new RoutedEventArgs());
            e.Handled = true;
        }
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        _pageCts = new CancellationTokenSource();
        if (e.Parameter is ReaderNavArgs args)
        {
            _bookId = args.BookId;
            TitleText.Text = args.Title;
            _pendingJump = args.SegmentIndex;
            _showRaw = LocalPrefs.GetShowRaw(_bookId);
            ShowRawToggle.IsChecked = _showRaw;
            ApplyFontSize();
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

    private void ApplyFontSize()
    {
        var size = LocalPrefs.ReaderFontSize;
        ThreeSentenceText.FontSize = size;
        KeyPointsText.FontSize = size - 1;
        WatchOutsText.FontSize = size - 1;
        BodyText.FontSize = size;
    }

    private void FontUp_Click(object sender, RoutedEventArgs e)
    {
        LocalPrefs.ReaderFontSize = Math.Min(28, LocalPrefs.ReaderFontSize + 1);
        ApplyFontSize();
    }

    private void FontDown_Click(object sender, RoutedEventArgs e)
    {
        LocalPrefs.ReaderFontSize = Math.Max(12, LocalPrefs.ReaderFontSize - 1);
        ApplyFontSize();
    }

    private async Task OpenAsync(ReaderNavArgs args)
    {
        SegmentLoading.IsActive = true;
        ThreeSentenceText.Text = "加载中…";
        try
        {
            var open = await App.Core.OpenBookAsync(args.BookId, _pageCts!.Token);
            var segments = await App.Core.ListSegmentsAsync(args.BookId, _pageCts.Token);
            _segments = segments.ToList();
            foreach (var s in _segments) s.RawText = null;
            SegmentList.ItemsSource = _segments;
            _totalCount = _segments.Count;
            _readyCount = _segments.Count(s => s.SummaryStatus is "ready" or "done");
            UpdateProgressBanner();

            var idx = _pendingJump ?? open.CurrentSegmentIndex;
            idx = Math.Clamp(idx, 0, Math.Max(0, _segments.Count - 1));
            if (_segments.Count > 0)
            {
                var listIdx = _segments.FindIndex(s => s.Idx == idx);
                SegmentList.SelectedIndex = listIdx >= 0 ? listIdx : idx;
            }
            StartEvents();
            await ReloadNotesAsync();
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            ThreeSentenceText.Text = ex.Message;
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
                if (!el.TryGetProperty("idx", out var idxEl) || !idxEl.TryGetInt32(out var idx)) continue;
                var row = _segments.FirstOrDefault(s => s.Idx == idx);
                if (row is null) continue;
                if (el.TryGetProperty("summary_status", out var st))
                    row.SummaryStatus = st.GetString() ?? row.SummaryStatus;
                if (el.TryGetProperty("label", out var lb) && lb.GetString() is { Length: > 0 } label)
                    row.Label = label;
                _hydrated.Remove(idx);
                _readyCount = _segments.Count(s => s.SummaryStatus is "ready" or "done");
                if (_selected?.Idx == idx) _ = HydrateSelectedAsync();
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
        await ReloadNotesAsync();
        try { _ = App.Core.SaveReadingProgressAsync(_bookId, row.Idx); }
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
            RenderContent(detail);
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            ThreeSentenceText.Text = ex.Message;
            KeyPointsText.Text = "";
            WatchOutsText.Text = "";
            FollowUpChips.ItemsSource = null;
            BodyText.Visibility = Visibility.Collapsed;
        }
        finally
        {
            SegmentLoading.IsActive = false;
        }
    }

    private void RenderContent(SegmentRow detail)
    {
        if (_showRaw)
        {
            ThreeSentenceText.Visibility = Visibility.Collapsed;
            KeyPointsText.Visibility = Visibility.Collapsed;
            WatchOutsText.Visibility = Visibility.Collapsed;
            FollowUpChips.Visibility = Visibility.Collapsed;
            BodyText.Visibility = Visibility.Visible;
            var raw = detail.RawText ?? "";
            var translation = string.IsNullOrWhiteSpace(detail.Translation)
                ? ""
                : $"\n\n—— 译文 ——\n{detail.Translation}";
            BodyText.Text = string.IsNullOrEmpty(raw) ? "（原文尚未加载）" : raw + translation;
            return;
        }

        BodyText.Visibility = Visibility.Collapsed;
        ThreeSentenceText.Visibility = Visibility.Visible;
        KeyPointsText.Visibility = Visibility.Visible;
        WatchOutsText.Visibility = Visibility.Visible;
        FollowUpChips.Visibility = Visibility.Visible;

        var parsed = SummaryJsonParser.Parse(detail.SummaryJson);
        if (!string.IsNullOrWhiteSpace(parsed.RawFallback) &&
            string.IsNullOrWhiteSpace(parsed.ThreeSentence) &&
            parsed.KeyPoints.Count == 0)
        {
            ThreeSentenceText.Text = parsed.RawFallback;
            KeyPointsText.Text = "";
            WatchOutsText.Text = "";
            FollowUpChips.ItemsSource = null;
            return;
        }

        ThreeSentenceText.Text = parsed.ThreeSentence
            ?? (detail.SummaryStatus is "ready" or "done" ? "（摘要为空）" : $"摘要状态：{detail.SummaryStatus}。可点击「开始摘要」。");
        KeyPointsText.Text = parsed.KeyPoints.Count == 0
            ? ""
            : "要点\n" + string.Join("\n", parsed.KeyPoints.Select(p => "• " + p));
        WatchOutsText.Text = parsed.WatchOuts.Count == 0
            ? ""
            : "需要注意\n" + string.Join("\n", parsed.WatchOuts.Select(p => "• " + p));
        FollowUpChips.ItemsSource = parsed.FollowUps;
    }

    private async void ShowRaw_Click(object sender, RoutedEventArgs e)
    {
        _showRaw = ShowRawToggle.IsChecked == true;
        LocalPrefs.SetShowRaw(_bookId, _showRaw);
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
        catch (Exception ex) { ProgressText.Text = ex.Message; }
    }

    private async void Regenerate_Click(object sender, RoutedEventArgs e)
    {
        var dlg = new ContentDialog
        {
            Title = "全书重新摘要",
            Content = "将重新生成全书段落摘要，可能耗时较长。",
            PrimaryButtonText = "开始",
            CloseButtonText = "取消",
            XamlRoot = XamlRoot,
        };
        if (await dlg.ShowAsync() != ContentDialogResult.Primary) return;
        try
        {
            await App.Core.RegenerateBookSummariesAsync(_bookId);
            ProgressText.Text = "已开始重新摘要";
            ProgressBanner.Visibility = Visibility.Visible;
        }
        catch (Exception ex) { ProgressText.Text = ex.Message; }
    }

    private async void RetrySegment_Click(object sender, RoutedEventArgs e)
    {
        if (_selected is null) return;
        try
        {
            await App.Core.RetrySegmentAsync(_bookId, _selected.Idx);
            ProgressText.Text = $"已重试段 {_selected.Idx + 1}";
            ProgressBanner.Visibility = Visibility.Visible;
        }
        catch (Exception ex) { ProgressText.Text = ex.Message; }
    }

    private void ToggleNotes_Click(object sender, RoutedEventArgs e)
    {
        NotesPanel.Visibility = NotesPanel.Visibility == Visibility.Visible
            ? Visibility.Collapsed
            : Visibility.Visible;
        if (NotesPanel.Visibility == Visibility.Visible)
            _ = ReloadNotesAsync();
    }

    private async void NotesFilter_Click(object sender, RoutedEventArgs e) => await ReloadNotesAsync();

    private async Task ReloadNotesAsync()
    {
        if (_selected is null) return;
        try
        {
            var currentOnly = NotesCurrentOnly.IsChecked == true;
            var notes = await App.Core.ListNotesAsync(
                bookId: _bookId,
                segmentId: currentOnly ? _selected.Id : null,
                ct: _pageCts?.Token ?? default);
            NotesList.ItemsSource = notes.ToList();
        }
        catch { /* panel optional */ }
    }

    private async void SaveNote_Click(object sender, RoutedEventArgs e)
    {
        if (_selected is null) return;
        var content = NoteInput.Text?.Trim();
        if (string.IsNullOrEmpty(content)) return;
        try
        {
            await App.Core.CreateNoteAsync(_bookId, content, _selected.Id);
            NoteInput.Text = "";
            await ReloadNotesAsync();
        }
        catch (Exception ex) { ProgressText.Text = ex.Message; ProgressBanner.Visibility = Visibility.Visible; }
    }

    private async void DeleteNotes_Click(object sender, RoutedEventArgs e)
    {
        var ids = NotesList.SelectedItems.OfType<NoteRow>().Select(n => n.Id).ToList();
        if (ids.Count == 0) return;
        try
        {
            await App.Core.DeleteNotesAsync(ids);
            await ReloadNotesAsync();
        }
        catch (Exception ex) { ProgressText.Text = ex.Message; }
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

    private void FollowUp_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button btn) return;
        var q = btn.Content?.ToString();
        if (string.IsNullOrWhiteSpace(q)) return;
        ChatPanel.Visibility = Visibility.Visible;
        ChatInput.Text = q;
        SendChat_Click(sender, e);
    }

    private void AskSelection_Click(object sender, RoutedEventArgs e)
    {
        var quote = BodyText.SelectedText;
        if (string.IsNullOrWhiteSpace(quote))
            quote = ThreeSentenceText.SelectedText;
        if (string.IsNullOrWhiteSpace(quote))
        {
            ProgressText.Text = "请先选中一段文字";
            ProgressBanner.Visibility = Visibility.Visible;
            return;
        }
        ChatPanel.Visibility = Visibility.Visible;
        ChatInput.Text = "请解释这段内容";
        _ = SendChatWithQuoteAsync(ChatInput.Text, quote);
    }

    private async void SendChat_Click(object sender, RoutedEventArgs e)
    {
        var message = ChatInput.Text?.Trim();
        if (string.IsNullOrEmpty(message)) return;
        ChatInput.Text = "";
        await SendChatWithQuoteAsync(message, null);
    }

    private async Task SendChatWithQuoteAsync(string message, string? quote)
    {
        if (_selected is null) return;
        _chat.Add(new ChatMessage { Role = "你", Content = quote is null ? message : $"{message}\n\n> {quote}" });
        var assistant = new ChatMessage { Role = "Lumina", Content = "" };
        _chat.Add(assistant);
        _lastAssistant = assistant;

        _chatCts?.Cancel();
        _chatCts = CancellationTokenSource.CreateLinkedTokenSource(_pageCts?.Token ?? default);
        var ct = _chatCts.Token;
        var idx = _selected.Idx;
        var lastFlush = DateTime.UtcNow;

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
                        if ((DateTime.UtcNow - lastFlush).TotalMilliseconds >= 200)
                        {
                            lastFlush = DateTime.UtcNow;
                            RefreshChatList();
                        }
                    });
                },
                quote: quote,
                ct: ct);

            assistant.Content = string.IsNullOrEmpty(resp.Answer) ? assistant.Content : resp.Answer;
            assistant.Citations = resp.Citations;
            assistant.ApplyMetrics(resp);
            if (resp.DurationMs is int ms || resp.Tps is not null)
            {
                var metrics = new List<string>();
                if (resp.Provider is not null) metrics.Add(resp.Provider);
                if (resp.Model is not null) metrics.Add(resp.Model);
                if (resp.DurationMs is int d) metrics.Add($"{d}ms");
                if (resp.Tps is double tps) metrics.Add($"{tps:0.0} tps");
                if (resp.TotalTokens is int tok) metrics.Add($"{tok} tok");
                if (metrics.Count > 0)
                    assistant.Content += "\n\n—" + string.Join(" · ", metrics);
            }
            if (resp.Citations.Count > 0)
            {
                assistant.Content += "\n\n引用：" + string.Join(
                    " ",
                    resp.Citations.Select(c => $"[段 {c.SegmentIndex + 1}]"));
                var jump = resp.Citations[0].SegmentIndex;
                var listIdx = _segments.FindIndex(s => s.Idx == jump);
                if (listIdx >= 0) SegmentList.SelectedIndex = listIdx;
            }
            RefreshChatList();
        }
        catch (OperationCanceledException)
        {
            assistant.Content += "\n（已取消）";
            RefreshChatList();
        }
        catch (Exception ex)
        {
            assistant.Content = ex.Message;
            RefreshChatList();
        }
    }

    private void RefreshChatList()
    {
        ChatList.ItemsSource = null;
        ChatList.ItemsSource = _chat;
    }

    private async void SaveChatAsNote_Click(object sender, RoutedEventArgs e)
    {
        if (_selected is null || _lastAssistant is null || string.IsNullOrWhiteSpace(_lastAssistant.Content))
            return;
        try
        {
            await App.Core.CreateNoteAsync(_bookId, _lastAssistant.Content, _selected.Id, type: "ai");
            await ReloadNotesAsync();
            ProgressText.Text = "已存为笔记";
            ProgressBanner.Visibility = Visibility.Visible;
        }
        catch (Exception ex) { ProgressText.Text = ex.Message; }
    }

    private async void Export_Click(object sender, RoutedEventArgs e)
    {
        var includeNotes = new CheckBox { Content = "包含笔记", IsChecked = true };
        var dlg = new ContentDialog
        {
            Title = "导出 Markdown",
            Content = includeNotes,
            PrimaryButtonText = "导出",
            CloseButtonText = "取消",
            XamlRoot = XamlRoot,
        };
        if (await dlg.ShowAsync() != ContentDialogResult.Primary) return;
        try
        {
            var md = await App.Core.ExportMarkdownAsync(_bookId, includeNotes.IsChecked == true);
            var window = MainWindowLocator.Current;
            if (window is null) return;
            var picker = new FileSavePicker();
            InitializeWithWindow.Initialize(picker, WindowNative.GetWindowHandle(window));
            picker.SuggestedFileName = $"{TitleText.Text}.md";
            picker.FileTypeChoices.Add("Markdown", [".md"]);
            var file = await picker.PickSaveFileAsync();
            if (file is null) return;
            await File.WriteAllTextAsync(file.Path, md);
            ProgressText.Text = "已导出";
            ProgressBanner.Visibility = Visibility.Visible;
        }
        catch (Exception ex)
        {
            ProgressText.Text = ex.Message;
            ProgressBanner.Visibility = Visibility.Visible;
        }
    }

    private void Back_Click(object sender, RoutedEventArgs e)
    {
        _pageCts?.Cancel();
        MainWindowLocator.Current?.NavigateToLibrary();
    }
}
