using System.Collections.ObjectModel;
using System.Text.Json;
using Lumina.Design;
using Lumina.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
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
    private DispatcherTimer? _progressTimer;
    private int _readyCount;
    private int _totalCount;
    private int? _pendingJump;
    private ChatMessage? _lastAssistant;
    private string _chatScope = "segment";
    private string _indexStatus = "idle";
    private long _lastSegmentTurnTick;

    public ReaderPage()
    {
        InitializeComponent();
        ChatList.ItemsSource = _chat;
        KeyDown += ReaderPage_KeyDown;
        CharacterReceived += ReaderPage_CharacterReceived;
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
            return;
        }

        if (e.Handled) return;
        if (ShouldIgnoreReaderScrollKey(e.OriginalSource as DependencyObject)) return;

        const double lineDelta = 80;
        var offset = ContentScroll.VerticalOffset;
        var viewport = ContentScroll.ViewportHeight;
        switch (e.Key)
        {
            case VirtualKey.Up:
                ContentScroll.ChangeView(null, Math.Max(0, offset - lineDelta), null);
                e.Handled = true;
                break;
            case VirtualKey.Down:
                ContentScroll.ChangeView(null, offset + lineDelta, null);
                e.Handled = true;
                break;
            case VirtualKey.PageUp:
                ContentScroll.ChangeView(null, Math.Max(0, offset - viewport * 0.9), null);
                e.Handled = true;
                break;
            case VirtualKey.PageDown:
                ContentScroll.ChangeView(null, offset + viewport * 0.9, null);
                e.Handled = true;
                break;
        }
    }

    private static bool ShouldIgnoreReaderScrollKey(DependencyObject? source)
    {
        var current = source;
        while (current != null)
        {
            if (current is TextBox or ComboBox or ListView or ListViewItem or Slider)
            {
                return true;
            }
            current = VisualTreeHelper.GetParent(current);
        }
        return false;
    }

    private void ReaderPage_CharacterReceived(UIElement sender, CharacterReceivedRoutedEventArgs e)
    {
        if (ShouldIgnoreReaderScrollKey(e.OriginalSource as DependencyObject)) return;
        var delta = e.Character switch
        {
            '[' or '【' => -1,
            ']' or '】' => 1,
            _ => 0,
        };
        if (delta == 0) return;
        if (TurnSegment(delta))
            e.Handled = true;
    }

    private void PrevSegment_Click(object sender, RoutedEventArgs e) => TurnSegment(-1);

    private void NextSegment_Click(object sender, RoutedEventArgs e) => TurnSegment(1);

    private bool TurnSegment(int delta)
    {
        if (_selected is null) return false;
        var sorted = _segments.Select(s => s.Idx).OrderBy(i => i).ToList();
        var target = SegmentTurnNavigation.TargetIdx(sorted, _selected.Idx, delta);
        if (target is not int idx) return false;
        var now = Environment.TickCount64;
        if (now - _lastSegmentTurnTick < 80) return false;
        var listIdx = _segments.FindIndex(s => s.Idx == idx);
        if (listIdx < 0) return false;
        _lastSegmentTurnTick = now;
        SegmentList.SelectedIndex = listIdx;
        return true;
    }

    private void UpdateSegmentTurnButtons()
    {
        var multi = _segments.Count > 1;
        PrevSegmentButton.Visibility = multi ? Visibility.Visible : Visibility.Collapsed;
        NextSegmentButton.Visibility = multi ? Visibility.Visible : Visibility.Collapsed;
        if (!multi || _selected is null)
        {
            PrevSegmentButton.IsEnabled = false;
            NextSegmentButton.IsEnabled = false;
            return;
        }
        var sorted = _segments.Select(s => s.Idx).OrderBy(i => i).ToList();
        PrevSegmentButton.IsEnabled =
            SegmentTurnNavigation.TargetIdx(sorted, _selected.Idx, -1) is not null;
        NextSegmentButton.IsEnabled =
            SegmentTurnNavigation.TargetIdx(sorted, _selected.Idx, 1) is not null;
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
            _chatScope = "segment";
            _indexStatus = "idle";
            if (ChatScopeBox is not null) ChatScopeBox.SelectedIndex = 0;
            ApplyFontSize();
            _ = OpenAsync(args);
        }
    }

    protected override void OnNavigatedFrom(NavigationEventArgs e)
    {
        PersistReadingProgress(patchServer: true);
        _progressTimer?.Stop();
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
            var book = await App.Core.FetchBookAsync(args.BookId, _pageCts.Token);
            _indexStatus = book.IndexStatus ?? "idle";
            var segments = await App.Core.ListSegmentsAsync(args.BookId, _pageCts.Token);
            _segments = segments.ToList();
            foreach (var s in _segments) s.RawText = null;
            SegmentList.ItemsSource = _segments;
            _totalCount = _segments.Count;
            _readyCount = _segments.Count(s => s.SummaryStatus is "ready" or "done");
            UpdateProgressBanner();
            UpdateChatScopeUi();

            var local = LocalPrefs.GetReadingProgress(_bookId, _segments.Count);
            var idx = _pendingJump ?? ReadingProgressIndex.Restore(
                open.CurrentSegmentIndex,
                local,
                local is null ? null : _segments.Count,
                _segments.Count);
            idx = Math.Clamp(idx, 0, Math.Max(0, _segments.Count - 1));
            if (_segments.Count > 0)
            {
                var listIdx = _segments.FindIndex(s => s.Idx == idx);
                SegmentList.SelectedIndex = listIdx >= 0 ? listIdx : idx;
            }
            UpdateSegmentTurnButtons();
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
                if (el.TryGetProperty("summary_tier", out var tier))
                    row.SummaryTier = tier.GetString();
                if (TryReadSummaryJson(el) is { Length: > 0 } summaryJson)
                    row.SummaryJson = summaryJson;
                _hydrated.Remove(idx);
                _readyCount = _segments.Count(s => s.SummaryStatus is "ready" or "done");
                if (_selected?.Idx == idx)
                {
                    if (!_showRaw && !string.IsNullOrEmpty(row.SummaryJson))
                        RenderContent(row);
                    _ = HydrateSelectedAsync();
                }
            }
            else if (type is "segment_boundary_moved")
            {
                ApplyBoundaryEvent(el, "left");
                ApplyBoundaryEvent(el, "right");
            }
            else if (type is "book_index_ready" or "book_index_progress")
            {
                if (el.TryGetProperty("index_status", out var st) && st.GetString() is string status)
                    _indexStatus = status;
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
        UpdateChatScopeUi();
    }

    private static string? TryReadSummaryJson(JsonElement el)
    {
        if (!el.TryGetProperty("summary_json", out var jsonEl)) return null;
        return jsonEl.ValueKind switch
        {
            JsonValueKind.String => jsonEl.GetString(),
            JsonValueKind.Object => jsonEl.GetRawText(),
            _ => null,
        };
    }

    private bool SummariesComplete => _totalCount > 0 && _readyCount >= _totalCount;

    /// <summary>True when picking 全书 should kick off the on-demand index build.</summary>
    private bool NeedsBookIndexBuild =>
        SummariesComplete && _indexStatus != "ready" && _indexStatus != "building";

    private void UpdateChatScopeUi()
    {
        var canBook = SummariesComplete && _indexStatus == "ready";
        if (ChatScopeBookItem is not null)
        {
            // Selectable while the index is missing so the user can trigger the build.
            ChatScopeBookItem.IsEnabled = canBook || NeedsBookIndexBuild;
            ChatScopeBookItem.Content = _indexStatus switch
            {
                "ready" => "全书",
                "building" => "全书（索引生成中）",
                _ => SummariesComplete ? "全书（点此建索引）" : "全书",
            };
        }
        if (!canBook && _chatScope == "book")
        {
            _chatScope = "segment";
            if (ChatScopeBox is not null) ChatScopeBox.SelectedIndex = 0;
        }
        if (ChatInput is not null)
            ChatInput.PlaceholderText = _chatScope == "book" ? "问全书…" : "针对本段提问…";
    }

    private void ChatScope_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (ChatScopeBox?.SelectedItem is ComboBoxItem { Tag: string tag })
            _chatScope = tag;
        else
            _chatScope = "segment";
        var shouldBuild = _chatScope == "book" && NeedsBookIndexBuild;
        UpdateChatScopeUi();
        if (shouldBuild) _ = BuildBookIndexAsync();
    }

    private async Task BuildBookIndexAsync()
    {
        if (string.IsNullOrEmpty(_bookId)) return;
        _indexStatus = "building";
        UpdateChatScopeUi();
        try
        {
            await App.Core.BuildBookIndexAsync(_bookId, _pageCts?.Token ?? default);
        }
        catch (OperationCanceledException)
        {
        }
        catch (Exception)
        {
            _indexStatus = "error";
            UpdateChatScopeUi();
        }
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
        UpdateSegmentTurnButtons();
        await HydrateSelectedAsync();
        await ReloadNotesAsync();
        SaveLocalProgress(row.Idx);
        try { _ = App.Core.SaveReadingProgressAsync(_bookId, row.Idx); }
        catch { /* non-blocking */ }
    }

    private void ContentScroll_ViewChanged(object sender, ScrollViewerViewChangedEventArgs e)
    {
        if (_selected is null) return;
        _progressTimer ??= new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(120) };
        _progressTimer.Tick -= ProgressTimer_Tick;
        _progressTimer.Tick += ProgressTimer_Tick;
        _progressTimer.Stop();
        _progressTimer.Start();
    }

    private void ProgressTimer_Tick(object sender, object e)
    {
        _progressTimer?.Stop();
        PersistReadingProgress(patchServer: false);
    }

    private void PersistReadingProgress(bool patchServer)
    {
        if (_selected is null || string.IsNullOrEmpty(_bookId)) return;
        SaveLocalProgress(_selected.Idx);
        if (!patchServer) return;
        try { _ = App.Core.SaveReadingProgressAsync(_bookId, _selected.Idx); }
        catch { /* non-blocking */ }
    }

    private void SaveLocalProgress(int index)
    {
        var percent = ReadingProgressIndex.Percent(index, _segments.Count);
        LocalPrefs.SetReadingProgress(_bookId, index, _segments.Count, 0, percent);
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
                    detail.SummaryTier = sum.SummaryTier;
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
            ?? SummaryStatusPlaceholder(detail.SummaryStatus);
        KeyPointsText.Text = parsed.KeyPoints.Count == 0
            ? ""
            : "要点\n" + string.Join("\n", parsed.KeyPoints.Select(p => "• " + p));
        WatchOutsText.Text = parsed.WatchOuts.Count == 0
            ? ""
            : "需要注意\n" + string.Join("\n", parsed.WatchOuts.Select(p => "• " + p));
        FollowUpChips.ItemsSource = parsed.FollowUps;
    }

    private static string SummaryStatusPlaceholder(string? status) => status switch
    {
        "ready" or "done" => "（摘要为空）",
        "running" => "摘要生成中…",
        "failed" or "error" => "摘要失败。可点击「开始摘要」重试。",
        _ => "尚无摘要。可点击「开始摘要」。",
    };

    private async void ShowRaw_Click(object sender, RoutedEventArgs e)
    {
        _showRaw = ShowRawToggle.IsChecked == true;
        LocalPrefs.SetShowRaw(_bookId, _showRaw);
        await HydrateSelectedAsync();
    }

    private static SummaryTier TierFromSender(object sender) =>
        (sender as FrameworkElement)?.Tag as string == "advanced"
            ? SummaryTier.Advanced
            : SummaryTier.Normal;

    private async void Summarize_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            await App.Core.StartSummarizeAsync(_bookId, TierFromSender(sender));
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
        var tier = TierFromSender(sender);
        var tierLabel = tier == SummaryTier.Advanced ? "高级摘要" : "正常摘要";
        var dlg = new ContentDialog
        {
            Title = "全书重新摘要",
            Content = $"将用「{tierLabel}」重新生成全书 {_totalCount} 个段的摘要。"
                + "已有摘要会被全部覆盖，会消耗大量计算和 API 资源，且无法撤销。"
                + "若只想用该档位补齐未摘要段落，请改用「开始摘要」。",
            PrimaryButtonText = "确认覆盖全书",
            CloseButtonText = "取消",
            DefaultButton = ContentDialogButton.Close,
            XamlRoot = XamlRoot,
        };
        if (await dlg.ShowAsync() != ContentDialogResult.Primary) return;
        try
        {
            await App.Core.RegenerateBookSummariesAsync(_bookId, tier);
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

    private async void AdjustBoundary_Click(object sender, RoutedEventArgs e)
    {
        if (_selected is null || _segments.Count < 2) return;
        var leftIdx = _selected.Idx >= _segments.Count - 1 ? _selected.Idx - 1 : _selected.Idx;
        try
        {
            var preview = await App.Core.FetchSegmentBoundaryAsync(_bookId, leftIdx);
            var left = await App.Core.GetSegmentAsync(_bookId, leftIdx);
            var right = await App.Core.GetSegmentAsync(_bookId, leftIdx + 1);
            var concat = (left.RawText ?? "") + (right.RawText ?? "");
            if (preview.Candidates.Count == 0)
            {
                ProgressText.Text = "这两段之间没有可调整的语义边界";
                ProgressBanner.Visibility = Visibility.Visible;
                return;
            }

            var index = preview.Candidates.FindIndex(c => c.Offset == preview.LeftCharCount);
            if (index < 0) index = 0;
            var leftPreview = new TextBlock { TextWrapping = TextWrapping.WrapWholeWords, MaxHeight = 120 };
            var rightPreview = new TextBlock { TextWrapping = TextWrapping.WrapWholeWords, MaxHeight = 120 };
            var counts = new TextBlock { Opacity = 0.7, Margin = new Thickness(0, 8, 0, 0) };
            var slider = new Slider
            {
                Minimum = 0,
                Maximum = Math.Max(0, preview.Candidates.Count - 1),
                Value = index,
                StepFrequency = 1,
                TickFrequency = 1,
                SnapsTo = SliderSnapsTo.Ticks,
            };
            void Render(int candidateIndex)
            {
                candidateIndex = Math.Clamp(candidateIndex, 0, preview.Candidates.Count - 1);
                var cut = preview.Candidates[candidateIndex].Offset;
                var leftText = cut <= concat.Length ? concat[..cut] : concat;
                var rightText = cut <= concat.Length ? concat[cut..] : "";
                leftPreview.Text = leftText.Length <= 360 ? leftText : leftText[^360..];
                rightPreview.Text = rightText.Length <= 360 ? rightText : rightText[..360];
                counts.Text = $"段 {leftIdx + 1} · {leftText.Length} 字    段 {leftIdx + 2} · {rightText.Length} 字";
            }
            slider.ValueChanged += (_, args) => Render((int)Math.Round(args.NewValue));
            Render(index);

            var panel = new StackPanel { Spacing = 8, MaxWidth = 560 };
            panel.Children.Add(new TextBlock
            {
                Text = "拖动滑块调整分界，切点会吸附到句子或段落边界。保存后只重新摘要这两段。",
                TextWrapping = TextWrapping.WrapWholeWords,
            });
            panel.Children.Add(leftPreview);
            panel.Children.Add(slider);
            panel.Children.Add(rightPreview);
            panel.Children.Add(counts);

            var dlg = new ContentDialog
            {
                Title = "调整分段",
                Content = panel,
                PrimaryButtonText = "保存并重新摘要",
                CloseButtonText = "取消",
                DefaultButton = ContentDialogButton.Primary,
                XamlRoot = XamlRoot,
            };
            if (await dlg.ShowAsync() != ContentDialogResult.Primary) return;
            var chosen = preview.Candidates[(int)Math.Round(slider.Value)].Offset;
            var result = await App.Core.MoveSegmentBoundaryAsync(_bookId, leftIdx, chosen);
            ApplyMoveResult(result);
            ProgressText.Text = result.Unchanged ? "分界未改变" : "已调整分界，正在重新摘要这两段";
            ProgressBanner.Visibility = Visibility.Visible;
            if (_selected?.Idx == leftIdx || _selected?.Idx == leftIdx + 1)
                await HydrateSelectedAsync();
        }
        catch (Exception ex)
        {
            ProgressText.Text = ex.Message;
            ProgressBanner.Visibility = Visibility.Visible;
        }
    }

    private void ApplyBoundaryEvent(JsonElement el, string side)
    {
        if (!el.TryGetProperty($"{side}_idx", out var idxEl) || !idxEl.TryGetInt32(out var idx))
            return;
        var row = _segments.FirstOrDefault(s => s.Idx == idx);
        if (row is null) return;
        if (el.TryGetProperty($"{side}_status", out var st))
            row.SummaryStatus = st.GetString() ?? "pending";
        else
            row.SummaryStatus = "pending";
        row.SummaryJson = null;
        row.Label = null;
        row.Translation = null;
        if (el.TryGetProperty($"{side}_anchor_label", out var anchor))
            row.AnchorLabel = anchor.GetString();
        if (el.TryGetProperty($"{side}_chapter", out var chapter))
            row.Chapter = chapter.GetString();
        if (el.TryGetProperty($"{side}_char_count", out var count) && count.TryGetInt32(out var chars))
            row.CharCount = chars;
        _hydrated.Remove(idx);
        _readyCount = _segments.Count(s => s.SummaryStatus is "ready" or "done");
        if (_selected?.Idx == idx) _ = HydrateSelectedAsync();
    }

    private void ApplyMoveResult(SegmentBoundaryMoveResult result)
    {
        ApplyMovedSide(result.LeftIdx, result.LeftStatus, result.LeftAnchorLabel, result.LeftChapter, result.LeftCharCount);
        ApplyMovedSide(result.RightIdx, result.RightStatus, result.RightAnchorLabel, result.RightChapter, result.RightCharCount);
        SegmentList.ItemsSource = null;
        SegmentList.ItemsSource = _segments;
    }

    private void ApplyMovedSide(int idx, string? status, string? anchor, string? chapter, int charCount)
    {
        var row = _segments.FirstOrDefault(s => s.Idx == idx);
        if (row is null) return;
        row.SummaryStatus = status ?? "pending";
        row.SummaryJson = null;
        row.Label = null;
        row.Translation = null;
        if (!string.IsNullOrEmpty(anchor)) row.AnchorLabel = anchor;
        row.Chapter = chapter;
        row.CharCount = charCount;
        _hydrated.Remove(idx);
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
                scope: _chatScope,
                onStatus: status => DispatcherQueue.TryEnqueue(() =>
                {
                    ChatStatusText.Text = status;
                    ChatStatusText.Visibility = Visibility.Visible;
                }),
                ct: ct);

            ChatStatusText.Visibility = Visibility.Collapsed;
            assistant.Content = string.IsNullOrEmpty(resp.Answer) ? assistant.Content : resp.Answer;
            assistant.Citations = resp.Citations;
            assistant.WebRefs = resp.WebRefs.Where(r => r.NavigateUri is not null).ToList();
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
            ChatStatusText.Visibility = Visibility.Collapsed;
            assistant.Content += "\n（已取消）";
            RefreshChatList();
        }
        catch (Exception ex)
        {
            ChatStatusText.Visibility = Visibility.Collapsed;
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

    private async void Import_Click(object sender, RoutedEventArgs e)
    {
        var window = MainWindowLocator.Current;
        if (window is null) return;

        var picker = new FileOpenPicker();
        InitializeWithWindow.Initialize(picker, WindowNative.GetWindowHandle(window));
        picker.FileTypeFilter.Add(".pdf");
        picker.FileTypeFilter.Add(".epub");
        picker.FileTypeFilter.Add(".mobi");
        picker.FileTypeFilter.Add(".txt");
        picker.FileTypeFilter.Add(".text");
        picker.FileTypeFilter.Add(".md");
        picker.FileTypeFilter.Add(".markdown");
        picker.FileTypeFilter.Add(".mdown");
        picker.FileTypeFilter.Add(".mkd");
        picker.FileTypeFilter.Add(".log");
        picker.FileTypeFilter.Add(".html");
        picker.FileTypeFilter.Add(".htm");
        picker.FileTypeFilter.Add(".xhtml");
        picker.FileTypeFilter.Add(".rtf");
        picker.FileTypeFilter.Add(".docx");
        picker.FileTypeFilter.Add(".odt");
        picker.FileTypeFilter.Add(".fb2");

        var files = await picker.PickMultipleFilesAsync();
        if (files is null || files.Count == 0) return;

        ProgressText.Text = $"导入中…（{files.Count} 个文件，可继续阅读）";
        ProgressBanner.Visibility = Visibility.Visible;
        foreach (var file in files)
        {
            try
            {
                await App.Core.ImportBookAsync(file.Path);
            }
            catch (ImportConflictException ex)
            {
                var dlg = new ContentDialog
                {
                    Title = "书已存在",
                    Content = $"「{ex.BookTitle}」已在书库中。",
                    PrimaryButtonText = "重新导入",
                    SecondaryButtonText = "打开已有",
                    CloseButtonText = "跳过",
                    XamlRoot = XamlRoot,
                };
                var result = await dlg.ShowAsync();
                if (result == ContentDialogResult.Primary)
                    await App.Core.ImportBookAsync(ex.Path, overwrite: true);
                else if (result == ContentDialogResult.Secondary && !string.IsNullOrEmpty(ex.ExistingBookId))
                    MainWindowLocator.Current?.NavigateToReader(ex.ExistingBookId, ex.BookTitle);
            }
            catch (Exception ex)
            {
                ProgressText.Text = $"导入失败：{ex.Message}";
                ProgressBanner.Visibility = Visibility.Visible;
                return;
            }
        }
        ProgressText.Text = "已加入书库，可继续阅读";
        ProgressBanner.Visibility = Visibility.Visible;
    }

    private void Back_Click(object sender, RoutedEventArgs e)
    {
        PersistReadingProgress(patchServer: true);
        _pageCts?.Cancel();
        MainWindowLocator.Current?.NavigateToLibrary();
    }
}
