using System.Collections.ObjectModel;
using System.Globalization;
using System.Text.Json;
using Lumina.Design;
using Lumina.Features.Library;
using Lumina.Features.Onboarding;
using Lumina.Features.Reader.Listen;
using Lumina.Features.Shared;
using Lumina.Services;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Input;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Documents;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Navigation;
using Windows.ApplicationModel.DataTransfer;
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
    private List<OriginalSearchHit> _originalHits = [];
    private int _originalHitIndex;
    private string _originalLastQuery = "";
    private CancellationTokenSource? _originalSearchCts;
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
    private string? _selectionQuote;
    private CancellationTokenSource? _selectionSaveCts;
    private double _selectionFlyoutScrollOffset;
    private Flyout? _selectionFlyout;
    private Button? _selectionWriteIdeaButton;
    private StackPanel? _selectionComposer;
    private TextBlock? _selectionQuoteBlock;
    private TextBox? _selectionIdeaInput;
    private TextBlock? _selectionIdeaError;
    private Button? _selectionSaveButton;
    private readonly HashSet<string> _collapsedChapters = new(StringComparer.Ordinal);
    private static readonly Dictionary<string, HashSet<string>> CollapsedByBook = new(StringComparer.Ordinal);
    private IReadOnlyList<SegmentCatalogItem> _catalog = [];
    private BookSummary? _book;
    private bool _isProcessing;
    private string? _processingKind;
    private DispatcherTimer? _flashTimer;
    private double _pendingOffsetY;
    private readonly ListenSession _listen;
    private bool _listenRateSuppress;

    public ReaderPage()
    {
        _listen = new ListenSession(DispatcherQueue.GetForCurrentThread());
        InitializeComponent();
        _listen.Changed += (_, _) => UpdateListenBar();
        _listen.HighlightSegment += idx => JumpToSegment(idx, flash: false);
        ChatList.ItemsSource = _chat;
        KeyDown += ReaderPage_KeyDown;
        CharacterReceived += ReaderPage_CharacterReceived;
    }

    internal FrameworkElement? TourTarget(OnboardingTourAnchor anchor) => anchor switch
    {
        OnboardingTourAnchor.Summarize => SummarizeAppBar,
        OnboardingTourAnchor.ModePicker => ShowRawToggle,
        OnboardingTourAnchor.Chat => ChatAppBar,
        OnboardingTourAnchor.Notes => NotesAppBar,
        _ => null,
    };

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
            if (current is TextBox or AutoSuggestBox or ComboBox or ListView or ListViewItem or Slider)
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
        var listItem = _catalog.FirstOrDefault(i => i.Segment?.Idx == idx);
        if (listItem is null) return false;
        _lastSegmentTurnTick = now;
        SegmentList.SelectedItem = listItem;
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
            RestoreCollapsedChapters(args.BookId);
            _bookId = args.BookId;
            TitleText.Text = args.Title;
            _pendingJump = args.SegmentIndex;
            _showRaw = LocalPrefs.GetShowRaw(_bookId);
            ShowRawToggle.IsChecked = _showRaw;
            _chatScope = "segment";
            _indexStatus = "idle";
            if (ChatScopeBox is not null) ChatScopeBox.SelectedIndex = 0;
            ApplyFontSize();
            ApplyPaper();
            _ = OpenAsync(args);
        }
    }

    protected override void OnNavigatedFrom(NavigationEventArgs e)
    {
        PersistCollapsedChapters();
        PersistReadingProgress(patchServer: true);
        _progressTimer?.Stop();
        _pageCts?.Cancel();
        _eventsCts?.Cancel();
        _chatCts?.Cancel();
        _hydrateCts?.Cancel();
        _originalSearchCts?.Cancel();
        _flushTimer?.Stop();
        _listen.Stop();
        DismissSelectionFlyout();
        base.OnNavigatedFrom(e);
    }

    private void ApplyFontSize()
    {
        var size = ReadingFontScale.Size(LocalPrefs.ReaderFontScale);
        LocalPrefs.ReaderFontSize = size;
        if (FontScaleLabel is not null)
            FontScaleLabel.Text = ReadingFontScale.Label(LocalPrefs.ReaderFontScale);
        ThreeSentenceText.FontSize = size;
        KeyPointsText.FontSize = size - 1;
        WatchOutsText.FontSize = size - 1;
        BodyText.FontSize = size;
    }

    private void ApplyPaper()
    {
        var kind = ReaderPaper.Parse(LocalPrefs.ReaderPaperRaw);
        var swatch = ReaderPaper.Swatch(kind);
        var page = new SolidColorBrush(Windows.UI.Color.FromArgb(255, swatch.PageR, swatch.PageG, swatch.PageB));
        var primary = new SolidColorBrush(Windows.UI.Color.FromArgb(255, swatch.TextR, swatch.TextG, swatch.TextB));
        var secondary = new SolidColorBrush(Windows.UI.Color.FromArgb(255, swatch.SecondaryR, swatch.SecondaryG, swatch.SecondaryB));
        ContentHighlight.Background = page;
        ThreeSentenceText.Foreground = primary;
        KeyPointsText.Foreground = primary;
        BodyText.Foreground = primary;
        SegmentTitle.Foreground = primary;
        WatchOutsText.Foreground = secondary;
        UpdatePaperButtons(kind);
    }

    private void UpdatePaperButtons(ReaderPaperKind kind)
    {
        var raw = ReaderPaper.RawValue(kind);
        foreach (var button in new[] { PaperWhiteBtn, PaperIvoryBtn, PaperSageBtn, PaperNightBtn })
        {
            if (button is null) continue;
            var on = button.Tag as string == raw;
            button.FontWeight = on ? Microsoft.UI.Text.FontWeights.SemiBold : Microsoft.UI.Text.FontWeights.Normal;
            button.Opacity = on ? 1 : 0.55;
        }
    }

    private void DisplayFlyout_Opened(object sender, object e) =>
        UpdatePaperButtons(ReaderPaper.Parse(LocalPrefs.ReaderPaperRaw));

    private void Paper_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button { Tag: string tag }) return;
        LocalPrefs.ReaderPaperRaw = tag;
        ApplyPaper();
    }

    private void FontUp_Click(object sender, RoutedEventArgs e)
    {
        LocalPrefs.ReaderFontScale = ReadingFontScale.Step(LocalPrefs.ReaderFontScale, 1);
        ApplyFontSize();
    }

    private void FontDown_Click(object sender, RoutedEventArgs e)
    {
        LocalPrefs.ReaderFontScale = ReadingFontScale.Step(LocalPrefs.ReaderFontScale, -1);
        ApplyFontSize();
    }

    private async Task OpenAsync(ReaderNavArgs args)
    {
        SegmentLoading.IsActive = true;
        ThreeSentenceText.Text = "加载中…";
        try
        {
            var book = await App.Core.FetchBookAsync(args.BookId, _pageCts!.Token);
            _book = book;
            _indexStatus = book.IndexStatus ?? "idle";
            TitleText.Text = string.IsNullOrWhiteSpace(book.Title) ? args.Title : book.Title;
            if (book.Status == "processing")
            {
                _isProcessing = true;
                _processingKind = book.ProcessingKind;
                ThreeSentenceText.Text = book.IsResegmenting
                    ? "正在重新分段。可以返回书架打开其他书籍，完成后会自动进入阅读。"
                    : "正在分段。可以返回书架打开其他书籍，完成后会自动进入阅读。";
                ProgressBanner.Visibility = Visibility.Visible;
                ProgressText.Text = book.IsResegmenting ? "正在重新分段…" : book.IngestProgressLabel;
                CancelProcessingBtn.Visibility = Visibility.Visible;
                StartEvents();
                return;
            }

            _isProcessing = false;
            CancelProcessingBtn.Visibility = Visibility.Collapsed;
            var open = await App.Core.OpenBookAsync(args.BookId, _pageCts.Token);
            var segments = await App.Core.ListSegmentsAsync(args.BookId, _pageCts.Token);
            _segments = segments.ToList();
            foreach (var s in _segments) s.RawText = null;
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
            _pendingOffsetY = ReadingProgressIndex.RestoreOffset(
                LocalPrefs.GetReadingProgressOffset(_bookId, _segments.Count),
                local is null ? null : _segments.Count,
                _segments.Count);
            BindSegmentCatalog(idx);
            UpdateSegmentTurnButtons();
            StartEvents();
            await ReloadNotesAsync();
            _listen.UpdateSegmentCount(_segments.Count);
            try
            {
                var settings = await App.Core.FetchSettingsAsync(_pageCts.Token);
                ListenPreferences.SyncFromSettings(settings.Models.Tts);
            }
            catch (OperationCanceledException) { throw; }
            catch { /* listen prefs stay at last local values */ }
            UpdateListenMenu();
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
                FillCatalogFields(row, el);
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
            else if (type is "ingest_progress")
            {
                if (!_isProcessing) continue;
                var msg = el.TryGetProperty("message", out var msgEl) ? msgEl.GetString() : null;
                ProgressBanner.Visibility = Visibility.Visible;
                ProgressText.Text = string.IsNullOrWhiteSpace(msg) ? "正在分段…" : msg;
                CancelProcessingBtn.Visibility = Visibility.Visible;
            }
            else if (type is "ingest_complete" or "ingest_cancelled" or "ingest_failed"
                     or "resegment_cancelled" or "resegment_failed")
            {
                _isProcessing = false;
                _ = OpenAsync(new ReaderNavArgs(_bookId, TitleText.Text));
                return;
            }
        }

        var selectedIdx = _selected?.Idx;
        BindSegmentCatalog(selectedIdx);
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

    private static void FillCatalogFields(SegmentRow row, JsonElement el)
    {
        if (el.TryGetProperty("bullet_labels", out var labelsEl)
            && labelsEl.ValueKind == JsonValueKind.Array)
        {
            var labels = new List<string>();
            foreach (var item in labelsEl.EnumerateArray())
            {
                var text = item.GetString()?.Trim();
                if (!string.IsNullOrEmpty(text)) labels.Add(text);
            }
            if (labels.Count > 0) row.BulletLabels = labels;
        }

        if (!string.IsNullOrEmpty(row.SummaryJson))
            FillCatalogFieldsFromSummaryJson(row);
    }

    private static void FillCatalogFieldsFromSummaryJson(SegmentRow row)
    {
        try
        {
            using var doc = JsonDocument.Parse(row.SummaryJson!);
            var root = doc.RootElement;
            if (string.IsNullOrWhiteSpace(row.SummaryPreview)
                && root.TryGetProperty("sentences", out var sentences)
                && sentences.ValueKind == JsonValueKind.Array)
            {
                foreach (var item in sentences.EnumerateArray())
                {
                    var text = item.GetString()?.Trim();
                    if (!string.IsNullOrEmpty(text))
                    {
                        row.SummaryPreview = text;
                        break;
                    }
                }
            }
            if ((row.BulletLabels is null || row.BulletLabels.Count == 0)
                && root.TryGetProperty("bullets", out var bullets)
                && bullets.ValueKind == JsonValueKind.Array)
            {
                var labels = new List<string>();
                foreach (var item in bullets.EnumerateArray())
                {
                    if (item.ValueKind == JsonValueKind.Object
                        && item.TryGetProperty("label", out var lb)
                        && lb.GetString() is { Length: > 0 } label)
                    {
                        labels.Add(label.Trim());
                    }
                    else if (item.ValueKind == JsonValueKind.String
                        && item.GetString() is { Length: > 0 } text)
                    {
                        var trimmed = text.Trim();
                        var cut = trimmed.IndexOf('：');
                        if (cut < 0) cut = trimmed.IndexOf(':');
                        if (cut > 0 && cut <= 12)
                            labels.Add(trimmed[..cut].Trim());
                        else
                            labels.Add(trimmed.Length <= 8 ? trimmed : trimmed[..8]);
                    }
                }
                if (labels.Count > 0) row.BulletLabels = labels;
            }
        }
        catch (JsonException)
        {
        }
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

    private void BindSegmentCatalog(int? keepIdx)
    {
        _catalog = SegmentCatalogPolicy.Build(_segments, _collapsedChapters);
        SegmentList.ItemsSource = _catalog;
        if (keepIdx is int idx)
        {
            var match = _catalog.FirstOrDefault(i => i.Segment?.Idx == idx);
            if (match is not null) SegmentList.SelectedItem = match;
        }
    }

    private void PersistCollapsedChapters()
    {
        if (string.IsNullOrEmpty(_bookId)) return;
        CollapsedByBook[_bookId] = new HashSet<string>(_collapsedChapters, StringComparer.Ordinal);
    }

    private void RestoreCollapsedChapters(string bookId)
    {
        if (!string.IsNullOrEmpty(_bookId) && _bookId != bookId)
            PersistCollapsedChapters();
        _collapsedChapters.Clear();
        if (CollapsedByBook.TryGetValue(bookId, out var saved))
        {
            foreach (var key in saved)
                _collapsedChapters.Add(key);
        }
    }

    private void JumpToSegment(int idx, bool flash)
    {
        var match = _catalog.FirstOrDefault(i => i.Segment?.Idx == idx);
        if (match is null)
        {
            var row = _segments.FirstOrDefault(s => s.Idx == idx);
            if (row is not null)
            {
                foreach (var key in SegmentCatalogPolicy.AncestorKeys(row))
                    _collapsedChapters.Remove(key);
                BindSegmentCatalog(idx);
                match = _catalog.FirstOrDefault(i => i.Segment?.Idx == idx);
            }
        }
        if (match is not null) SegmentList.SelectedItem = match;
        if (flash) FlashContent();
    }

    private void FlashContent()
    {
        ContentHighlight.Background = new SolidColorBrush(Windows.UI.Color.FromArgb(80, 196, 90, 30));
        _flashTimer?.Stop();
        _flashTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(700) };
        _flashTimer.Tick += (_, _) =>
        {
            _flashTimer?.Stop();
            ApplyPaper();
        };
        _flashTimer.Start();
    }

    private void UpdateProgressBanner()
    {
        if (_isProcessing)
        {
            ProgressBanner.Visibility = Visibility.Visible;
            CancelProcessingBtn.Visibility = Visibility.Visible;
            if (string.IsNullOrWhiteSpace(ProgressText.Text))
                ProgressText.Text = "正在处理…";
            return;
        }
        CancelProcessingBtn.Visibility = Visibility.Collapsed;
        if (_totalCount <= 0)
        {
            ProgressBanner.Visibility = Visibility.Collapsed;
            return;
        }
        ProgressBanner.Visibility = Visibility.Visible;
        ProgressText.Text = $"摘要进度 {_readyCount}/{_totalCount}";
    }

    private async void CancelProcessing_Click(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrEmpty(_bookId)) return;
        try
        {
            if (string.Equals(_processingKind, "resegment", StringComparison.Ordinal))
                await App.Core.CancelResegmentBookAsync(_bookId, _pageCts?.Token ?? default);
            else
                await App.Core.CancelIngestAsync(_bookId, _pageCts?.Token ?? default);
            ProgressText.Text = "已请求取消";
        }
        catch (Exception ex)
        {
            ProgressText.Text = ex.Message;
        }
    }

    private async void SegmentList_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (SegmentList.SelectedItem is not SegmentCatalogItem item) return;
        if (item.IsHeader)
        {
            if (_collapsedChapters.Contains(item.ChapterKey))
                _collapsedChapters.Remove(item.ChapterKey);
            else
                _collapsedChapters.Add(item.ChapterKey);
            BindSegmentCatalog(_selected?.Idx);
            return;
        }
        if (item.Segment is null) return;
        DismissSelectionFlyout();
        _selected = item.Segment;
        UpdateSegmentTurnButtons();
        await HydrateSelectedAsync();
        await ReloadNotesAsync();
        SaveLocalProgress(item.Segment.Idx);
        try { _ = App.Core.SaveReadingProgressAsync(_bookId, item.Segment.Idx); }
        catch { /* non-blocking */ }
    }

    private void ContentScroll_ViewChanged(object sender, ScrollViewerViewChangedEventArgs e)
    {
        if (_selectionFlyout?.IsOpen == true
            && Math.Abs(ContentScroll.VerticalOffset - _selectionFlyoutScrollOffset) > 2)
        {
            DismissSelectionFlyout();
        }
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
        LocalPrefs.SetReadingProgress(_bookId, index, _segments.Count, ContentScroll.VerticalOffset, percent);
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
            var detail = await LoadSegmentDetailAsync(idx, _showRaw, ct);
            ct.ThrowIfCancellationRequested();
            SegmentTitle.Text = detail.DisplayLabel;
            RenderContent(detail);
            if (_pendingOffsetY > 0)
            {
                var y = _pendingOffsetY;
                _pendingOffsetY = 0;
                DispatcherQueue.TryEnqueue(() =>
                    ContentScroll.ChangeView(null, y, null, disableAnimation: true));
            }
            _ = PrefetchNeighborsAsync(idx);
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

    private async Task<SegmentRow> LoadSegmentDetailAsync(int idx, bool needRaw, CancellationToken ct)
    {
        if (_hydrated.TryGetValue(idx, out var cached)
            && (!needRaw || !string.IsNullOrEmpty(cached.RawText))
            && (needRaw || !string.IsNullOrEmpty(cached.SummaryJson) || cached.SummaryStatus is not ("ready" or "done")))
        {
            return cached;
        }

        SegmentRow detail;
        if (needRaw)
        {
            detail = await App.Core.GetSegmentAsync(_bookId, idx, ct);
            if (string.IsNullOrEmpty(detail.SummaryJson) && detail.SummaryStatus is "ready" or "done")
            {
                var sum = await App.Core.FetchSegmentSummaryAsync(_bookId, idx, ct);
                ApplySummaryDetail(detail, sum);
            }
        }
        else
        {
            var catalog = _segments.FirstOrDefault(s => s.Idx == idx) ?? new SegmentRow { Idx = idx };
            detail = CloneCatalog(catalog);
            if (detail.SummaryStatus is "ready" or "done" || string.IsNullOrEmpty(detail.SummaryJson))
            {
                var sum = await App.Core.FetchSegmentSummaryAsync(_bookId, idx, ct);
                ApplySummaryDetail(detail, sum);
            }
        }
        _hydrated[idx] = detail;
        return detail;
    }

    private static SegmentRow CloneCatalog(SegmentRow src) => new()
    {
        Id = src.Id,
        Idx = src.Idx,
        Label = src.Label,
        Chapter = src.Chapter,
        SummaryStatus = src.SummaryStatus,
        SummaryJson = src.SummaryJson,
        AnchorLabel = src.AnchorLabel,
        SummaryTier = src.SummaryTier,
        SummaryPreview = src.SummaryPreview,
        BulletLabels = src.BulletLabels,
    };

    private static void ApplySummaryDetail(SegmentRow detail, SegmentSummaryDetail sum)
    {
        if (!string.IsNullOrEmpty(sum.SummaryJson)) detail.SummaryJson = sum.SummaryJson;
        if (!string.IsNullOrEmpty(sum.Label)) detail.Label = sum.Label;
        if (!string.IsNullOrEmpty(sum.SummaryTier)) detail.SummaryTier = sum.SummaryTier;
        if (!string.IsNullOrEmpty(sum.SummaryStatus)) detail.SummaryStatus = sum.SummaryStatus;
        if (!string.IsNullOrEmpty(sum.AnchorLabel)) detail.AnchorLabel = sum.AnchorLabel;
    }

    private async Task PrefetchNeighborsAsync(int idx)
    {
        var sorted = _segments.Select(s => s.Idx).OrderBy(i => i).ToList();
        var neighbors = NeighborPrefetchPolicy.Neighbors(idx, sorted);
        var ct = _pageCts?.Token ?? default;
        foreach (var n in neighbors)
        {
            if (ct.IsCancellationRequested) return;
            try
            {
                await LoadSegmentDetailAsync(n, NeighborPrefetchPolicy.NeedsRawText(_showRaw), ct);
            }
            catch (OperationCanceledException) { return; }
            catch { /* prefetch is best-effort */ }
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
            RenderOriginalBody(raw, detail.Translation);
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
        DismissSelectionFlyout();
        _showRaw = ShowRawToggle.IsChecked == true;
        LocalPrefs.SetShowRaw(_bookId, _showRaw);
        UpdateListenMenu();
        await HydrateSelectedAsync();
    }

    private OriginalSearchHit? CurrentOriginalHitFor(int segmentIdx)
    {
        if (_originalHitIndex < 0 || _originalHitIndex >= _originalHits.Count) return null;
        var hit = _originalHits[_originalHitIndex];
        return hit.SegmentIndex == segmentIdx ? hit : null;
    }

    private void RenderOriginalBody(string raw, string? translation)
    {
        BodyText.Inlines.Clear();
        if (string.IsNullOrEmpty(raw))
        {
            BodyText.Text = "（原文尚未加载）";
            return;
        }

        var hit = _selected is null ? null : CurrentOriginalHitFor(_selected.Idx);
        var start = hit?.StartUtf16 ?? -1;
        var end = hit?.EndUtf16 ?? -1;
        if (hit is null || start < 0 || end > raw.Length || end <= start)
        {
            BodyText.Inlines.Add(new Run { Text = raw });
        }
        else
        {
            if (start > 0)
                BodyText.Inlines.Add(new Run { Text = raw[..start] });
            BodyText.Inlines.Add(new Run
            {
                Text = raw[start..end],
                Foreground = new SolidColorBrush(Windows.UI.Color.FromArgb(255, 196, 90, 30)),
            });
            if (end < raw.Length)
                BodyText.Inlines.Add(new Run { Text = raw[end..] });
            DispatcherQueue.TryEnqueue(() => ScrollOriginalHitIntoView(start, raw.Length));
        }

        if (!string.IsNullOrWhiteSpace(translation))
            BodyText.Inlines.Add(new Run { Text = $"\n\n—— 译文 ——\n{translation}" });
    }

    private void ScrollOriginalHitIntoView(int utf16Start, int rawLength)
    {
        if (rawLength <= 0 || BodyText.ActualHeight <= 0) return;
        try
        {
            var origin = BodyText.TransformToVisual(ContentScroll)
                .TransformPoint(new Windows.Foundation.Point(0, 0));
            var ratio = (double)utf16Start / rawLength;
            var y = origin.Y + ContentScroll.VerticalOffset + BodyText.ActualHeight * ratio - 72;
            ContentScroll.ChangeView(null, Math.Max(0, y), null, disableAnimation: true);
        }
        catch (Exception)
        {
            // Layout not ready; skip intra-segment scroll.
        }
    }

    private void UpdateOriginalSearchChrome()
    {
        var count = _originalHits.Count;
        OriginalSearchPrev.IsEnabled = count > 0;
        OriginalSearchNext.IsEnabled = count > 0;
        OriginalSearchStatus.Text = count == 0
            ? (string.IsNullOrEmpty(_originalLastQuery) ? "" : "无匹配")
            : $"{_originalHitIndex + 1}/{count}";
    }

    private void OriginalSearch_Accelerator(KeyboardAccelerator sender, KeyboardAcceleratorInvokedEventArgs args)
    {
        OriginalSearchBox.Focus(FocusState.Programmatic);
        args.Handled = true;
    }

    private async void OriginalSearch_QuerySubmitted(AutoSuggestBox sender, AutoSuggestBoxQuerySubmittedEventArgs args)
    {
        var q = (args.QueryText ?? sender.Text ?? "").Trim();
        if (string.IsNullOrEmpty(q) || string.IsNullOrEmpty(_bookId)) return;
        if (q == _originalLastQuery && _originalHits.Count > 0)
        {
            StepOriginalSearch(1);
            return;
        }
        await RunOriginalSearchAsync(q);
    }

    private async Task RunOriginalSearchAsync(string query)
    {
        _originalSearchCts?.Cancel();
        _originalSearchCts = new CancellationTokenSource();
        var ct = _originalSearchCts.Token;
        _originalLastQuery = query;
        try
        {
            var result = await App.Core.SearchOriginalAsync(_bookId, query, ct).ConfigureAwait(true);
            if (ct.IsCancellationRequested) return;
            _originalHits = result.Hits;
            _originalHitIndex = 0;
            UpdateOriginalSearchChrome();
            if (_originalHits.Count == 0) return;
            await LocateOriginalSearchHitAsync();
        }
        catch (OperationCanceledException)
        {
        }
        catch (Exception ex)
        {
            OriginalSearchStatus.Text = ex.Message;
        }
    }

    private void OriginalSearchPrev_Click(object sender, RoutedEventArgs e) => StepOriginalSearch(-1);

    private void OriginalSearchNext_Click(object sender, RoutedEventArgs e) => StepOriginalSearch(1);

    private void StepOriginalSearch(int delta)
    {
        if (_originalHits.Count == 0) return;
        _originalHitIndex = (_originalHitIndex + delta) % _originalHits.Count;
        if (_originalHitIndex < 0) _originalHitIndex += _originalHits.Count;
        UpdateOriginalSearchChrome();
        _ = LocateOriginalSearchHitAsync();
    }

    private async Task LocateOriginalSearchHitAsync()
    {
        if (_originalHitIndex < 0 || _originalHitIndex >= _originalHits.Count) return;
        var hit = _originalHits[_originalHitIndex];
        if (!_showRaw)
        {
            _showRaw = true;
            ShowRawToggle.IsChecked = true;
            LocalPrefs.SetShowRaw(_bookId, true);
            UpdateListenMenu();
        }
        var listIdx = _segments.FindIndex(s => s.Idx == hit.SegmentIndex);
        if (listIdx >= 0 && SegmentList.SelectedIndex != listIdx)
            SegmentList.SelectedIndex = listIdx;
        else
            await HydrateSelectedAsync();
    }

    private static SummaryTier TierFromSender(object sender) =>
        (sender as FrameworkElement)?.Tag as string == "advanced"
            ? SummaryTier.Advanced
            : SummaryTier.Normal;

    private async void StartSummarizeNormal_Click(object sender, RoutedEventArgs e) =>
        await StartSummarizeAsync(SummaryTier.Normal);

    private async void StartSummarizeAdvanced_Click(object sender, RoutedEventArgs e)
    {
        HideSummarizeFlyouts();
        if (!await ConfirmAdvancedStartAsync()) return;
        await StartSummarizeAsync(SummaryTier.Advanced);
    }

    private void HideSummarizeFlyouts()
    {
        StartSummarizeSplit.Flyout?.Hide();
        RegenerateSummarizeSplit.Flyout?.Hide();
        SummarizeAppBar.Flyout?.Hide();
    }

    private async Task<bool> ConfirmAdvancedStartAsync()
    {
        var dlg = new ContentDialog
        {
            Title = "高级摘要",
            Content = "将用高级模型补齐尚未摘要的段落，消耗更多计算与 API。已有摘要不会被覆盖。",
            PrimaryButtonText = "开始高级摘要",
            CloseButtonText = "取消",
            DefaultButton = ContentDialogButton.Close,
            XamlRoot = XamlRoot,
        };
        return await dlg.ShowAsync() == ContentDialogResult.Primary;
    }

    private async Task StartSummarizeAsync(SummaryTier tier)
    {
        try
        {
            await App.Core.StartSummarizeAsync(_bookId, tier);
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

    private async void RegenerateNormal_Click(object sender, RoutedEventArgs e) =>
        await ConfirmAndRegenerateAsync(SummaryTier.Normal);

    private async void Regenerate_Click(object sender, RoutedEventArgs e) =>
        await ConfirmAndRegenerateAsync(TierFromSender(sender));

    private async Task ConfirmAndRegenerateAsync(SummaryTier tier)
    {
        HideSummarizeFlyouts();
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
            var left = await App.Core.GetSegmentAsync(_bookId, leftIdx);
            var right = await App.Core.GetSegmentAsync(_bookId, leftIdx + 1);
            var concat = (left.RawText ?? "") + (right.RawText ?? "");
            if (string.IsNullOrEmpty(concat))
            {
                ProgressText.Text = "这两段没有可调整的正文";
                ProgressBanner.Visibility = Visibility.Visible;
                return;
            }

            var originalCut = (left.RawText ?? "").EnumerateRunes().Count();
            var previewCut = originalCut;
            var total = concat.EnumerateRunes().Count();
            var candidateOffsets = new List<int>();
            try
            {
                var preview = await App.Core.FetchSegmentBoundaryAsync(_bookId, leftIdx);
                candidateOffsets = preview.Candidates?.ConvertAll(c => c.Offset) ?? [];
            }
            catch
            {
                // Preview still works at the raw click; the server snaps on save.
            }
            var (leftText, rightText) = SegmentBoundaryOffset.Split(concat, previewCut);
            var counts = new TextBlock
            {
                Opacity = 0.7,
                Text = $"段 {leftIdx + 1} · {leftText.EnumerateRunes().Count()} 字    段 {leftIdx + 2} · {rightText.EnumerateRunes().Count()} 字",
            };
            var error = new TextBlock
            {
                TextWrapping = TextWrapping.WrapWholeWords,
                Visibility = Visibility.Collapsed,
            };
            var editor = new TextBox
            {
                Text = concat,
                AcceptsReturn = true,
                TextWrapping = TextWrapping.Wrap,
                IsReadOnly = true,
                MinHeight = 220,
            };
            var scroller = new ScrollViewer
            {
                Content = editor,
                MaxHeight = 320,
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
            };
            var saving = new ProgressRing { IsActive = false, Width = 28, Height = 28, Visibility = Visibility.Collapsed };
            var panel = new StackPanel { Spacing = 8, MaxWidth = 640 };
            panel.Children.Add(new TextBlock
            {
                Text = "点击正文中要作为新分界的位置。切点会吸附到最近的句子或段落。点「保存」才落库并重新摘要这两段；取消不保存。",
                TextWrapping = TextWrapping.WrapWholeWords,
            });
            panel.Children.Add(counts);
            panel.Children.Add(scroller);
            panel.Children.Add(error);
            panel.Children.Add(saving);

            var dlg = new ContentDialog
            {
                Title = "调整分段",
                Content = panel,
                PrimaryButtonText = "保存",
                CloseButtonText = "取消",
                DefaultButton = ContentDialogButton.Primary,
                IsPrimaryButtonEnabled = false,
                XamlRoot = XamlRoot,
            };
            var isSaving = false;
            void RefreshPreview()
            {
                var (nextLeft, nextRight) = SegmentBoundaryOffset.Split(concat, previewCut);
                counts.Text = $"段 {leftIdx + 1} · {nextLeft.EnumerateRunes().Count()} 字    段 {leftIdx + 2} · {nextRight.EnumerateRunes().Count()} 字";
                var caret = SegmentBoundaryOffset.Utf16Index(concat, previewCut);
                editor.Select(caret, 0);
                dlg.IsPrimaryButtonEnabled = SegmentBoundaryOffset.CanSave(
                    previewCut, originalCut, total, isSaving);
            }
            editor.PointerReleased += (_, _) =>
            {
                if (isSaving || editor.SelectionLength > 0) return;
                var offset = SegmentBoundaryOffset.NearestOffset(
                    SegmentBoundaryOffset.UnicodeOffset(concat, editor.SelectionStart),
                    candidateOffsets);
                if (offset <= 0 || offset >= total)
                {
                    error.Text = "调整后两侧都必须保留正文";
                    error.Visibility = Visibility.Visible;
                    return;
                }
                error.Visibility = Visibility.Collapsed;
                previewCut = offset;
                RefreshPreview();
            };
            dlg.PrimaryButtonClick += async (_, args) =>
            {
                var deferral = args.GetDeferral();
                try
                {
                    if (!SegmentBoundaryOffset.CanSave(previewCut, originalCut, total, isSaving))
                    {
                        args.Cancel = true;
                        return;
                    }
                    isSaving = true;
                    dlg.IsPrimaryButtonEnabled = false;
                    editor.IsEnabled = false;
                    error.Visibility = Visibility.Collapsed;
                    saving.Visibility = Visibility.Visible;
                    saving.IsActive = true;
                    var result = await App.Core.MoveSegmentBoundaryAsync(_bookId, leftIdx, previewCut);
                    ApplyMoveResult(result);
                    ProgressText.Text = result.Unchanged ? "分界未改变" : "已调整分界，正在重新摘要这两段";
                    ProgressBanner.Visibility = Visibility.Visible;
                    isSaving = false;
                    if (_selected?.Idx == leftIdx || _selected?.Idx == leftIdx + 1)
                    {
                        try { await HydrateSelectedAsync(); }
                        catch { /* boundary already saved */ }
                    }
                }
                catch (Exception ex)
                {
                    args.Cancel = true;
                    error.Text = ex.Message;
                    error.Visibility = Visibility.Visible;
                    editor.IsEnabled = true;
                    isSaving = false;
                    RefreshPreview();
                }
                finally
                {
                    saving.IsActive = false;
                    saving.Visibility = Visibility.Collapsed;
                    deferral.Complete();
                }
            };
            dlg.Closing += (_, args) =>
            {
                if (isSaving) args.Cancel = true;
            };

            await dlg.ShowAsync();
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

    private void DismissSelectionFlyout()
    {
        _selectionSaveCts?.Cancel();
        _selectionSaveCts = null;
        if (_selectionFlyout?.IsOpen == true)
            _selectionFlyout.Hide();
        if (_selectionComposer is not null)
            _selectionComposer.Visibility = Visibility.Collapsed;
        if (_selectionIdeaError is not null)
            _selectionIdeaError.Visibility = Visibility.Collapsed;
        if (_selectionSaveButton is not null)
            _selectionSaveButton.IsEnabled = false;
    }

    private Flyout EnsureSelectionFlyout()
    {
        if (_selectionFlyout is not null) return _selectionFlyout;

        var copy = new Button { Content = "复制" };
        AutomationProperties.SetAutomationId(copy, "lumina.reader.selection.copy");
        copy.Click += SelectionCopy_Click;

        _selectionWriteIdeaButton = new Button { Content = "写想法" };
        AutomationProperties.SetAutomationId(_selectionWriteIdeaButton, "lumina.reader.selection.writeIdea");
        _selectionWriteIdeaButton.Click += SelectionWriteIdea_Click;

        var actions = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        actions.Children.Add(copy);
        actions.Children.Add(_selectionWriteIdeaButton);
        var ask = new Button { Content = "提问" };
        AutomationProperties.SetAutomationId(ask, "lumina.reader.selection.ask");
        ask.Click += SelectionAsk_Click;
        actions.Children.Add(ask);

        _selectionQuoteBlock = new TextBlock { TextWrapping = TextWrapping.WrapWholeWords, MaxLines = 4 };
        _selectionIdeaInput = new TextBox { PlaceholderText = "写想法…", AcceptsReturn = true };
        _selectionIdeaInput.TextChanged += SelectionIdeaInput_TextChanged;
        _selectionIdeaError = new TextBlock
        {
            Visibility = Visibility.Collapsed,
            TextWrapping = TextWrapping.WrapWholeWords,
        };
        _selectionSaveButton = new Button
        {
            Content = "保存",
            IsEnabled = false,
            HorizontalAlignment = HorizontalAlignment.Right,
        };
        AutomationProperties.SetAutomationId(_selectionSaveButton, "lumina.reader.selection.save");
        _selectionSaveButton.Click += SelectionSave_Click;

        _selectionComposer = new StackPanel { Spacing = 8, Visibility = Visibility.Collapsed };
        _selectionComposer.Children.Add(_selectionQuoteBlock);
        _selectionComposer.Children.Add(_selectionIdeaInput);
        _selectionComposer.Children.Add(_selectionIdeaError);
        _selectionComposer.Children.Add(_selectionSaveButton);

        var root = new StackPanel { Width = 280, Spacing = 8 };
        root.Children.Add(actions);
        root.Children.Add(_selectionComposer);

        _selectionFlyout = new Flyout { Placement = FlyoutPlacementMode.Top, Content = root };
        return _selectionFlyout;
    }

    private void SelectableText_PointerReleased(object sender, PointerRoutedEventArgs e)
    {
        if (sender is not TextBlock block) return;
        if (e.GetCurrentPoint(block).Properties.PointerUpdateKind
            != PointerUpdateKind.LeftButtonReleased)
        {
            return;
        }
        if (!SelectionActionPolicy.ShouldShowMenu(block.SelectedText)) return;
        var quote = SelectionActionPolicy.CapturedQuote(block.SelectedText);
        if (quote is null) return;

        _selectionQuote = quote;
        var flyout = EnsureSelectionFlyout();
        if (_selectionComposer is not null)
            _selectionComposer.Visibility = Visibility.Collapsed;
        if (_selectionQuoteBlock is not null)
            _selectionQuoteBlock.Text = $"「{quote}」";
        if (_selectionIdeaInput is not null)
            _selectionIdeaInput.Text = "";
        if (_selectionIdeaError is not null)
        {
            _selectionIdeaError.Visibility = Visibility.Collapsed;
            _selectionIdeaError.Text = "";
        }
        if (_selectionSaveButton is not null)
            _selectionSaveButton.IsEnabled = false;
        if (_selectionWriteIdeaButton is not null)
        {
            _selectionWriteIdeaButton.Visibility = _selected is null
                ? Visibility.Collapsed
                : Visibility.Visible;
        }

        _selectionFlyoutScrollOffset = ContentScroll.VerticalOffset;
        flyout.ShowAt(block, new FlyoutShowOptions
        {
            Position = e.GetCurrentPoint(block).Position,
            Placement = FlyoutPlacementMode.Top,
            ShowMode = FlyoutShowMode.Standard,
        });
    }

    private void SelectionCopy_Click(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrEmpty(_selectionQuote)) return;
        var data = new DataPackage();
        data.SetText(_selectionQuote);
        Clipboard.SetContent(data);
        DismissSelectionFlyout();
    }

    private void SelectionAsk_Click(object sender, RoutedEventArgs e)
    {
        DismissSelectionFlyout();
        AskSelection_Click(sender, e);
    }

    private void Citation_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not HyperlinkButton btn) return;
        var idx = btn.Tag switch
        {
            int i => i,
            string s when int.TryParse(s, out var parsed) => parsed,
            _ => -1,
        };
        if (ChatCitationJumpPolicy.TargetIdx(idx) is not int target) return;
        JumpToSegment(target, flash: true);
    }

    private async void ResegmentBook_Click(object sender, RoutedEventArgs e)
    {
        var book = _book ?? (string.IsNullOrEmpty(_bookId) ? null : await App.Core.FetchBookAsync(_bookId));
        if (book is null) return;
        var choice = await ResegmentBookDialog.ShowAsync(XamlRoot, book);
        if (choice is null) return;
        try
        {
            LocalPrefs.ClearCachedProgress(_bookId);
            await App.Core.ResegmentBookAsync(_bookId, choice.Value.ChunkTargetChars, choice.Value.Tier);
            _isProcessing = true;
            _processingKind = "resegment";
            ProgressBanner.Visibility = Visibility.Visible;
            ProgressText.Text = "正在重新分段…";
            CancelProcessingBtn.Visibility = Visibility.Visible;
            ThreeSentenceText.Text = "正在重新分段。可以返回书架，完成后会自动进入阅读。";
        }
        catch (Exception ex)
        {
            ProgressText.Text = ex.Message;
            ProgressBanner.Visibility = Visibility.Visible;
        }
    }

    private async void RetrySelectedSegments_Click(object sender, RoutedEventArgs e)
    {
        var failed = SegmentList.SelectedItems
            .OfType<SegmentCatalogItem>()
            .Select(i => i.Segment)
            .Where(s => s is not null && s.SummaryStatus is "failed" or "error")
            .Select(s => s!.Idx)
            .Distinct()
            .ToList();
        if (failed.Count == 0)
        {
            ProgressText.Text = "请多选失败的段后再试";
            ProgressBanner.Visibility = Visibility.Visible;
            return;
        }
        try
        {
            await App.Core.RetrySegmentsAsync(_bookId, failed);
            ProgressText.Text = $"已重试 {failed.Count} 段";
            ProgressBanner.Visibility = Visibility.Visible;
        }
        catch (Exception ex) { ProgressText.Text = ex.Message; }
    }

    private void SelectionWriteIdea_Click(object sender, RoutedEventArgs e)
    {
        if (_selected is null) return;
        if (_selectionComposer is not null)
            _selectionComposer.Visibility = Visibility.Visible;
        _selectionIdeaInput?.Focus(FocusState.Programmatic);
    }

    private void SelectionIdeaInput_TextChanged(object sender, TextChangedEventArgs e)
    {
        var hasText = !string.IsNullOrWhiteSpace(_selectionIdeaInput?.Text);
        if (_selectionSaveButton is not null)
            _selectionSaveButton.IsEnabled = hasText && _selected is not null;
    }

    private async void SelectionSave_Click(object sender, RoutedEventArgs e)
    {
        if (_selected is null) return;
        var content = _selectionIdeaInput?.Text?.Trim();
        if (string.IsNullOrEmpty(content) || string.IsNullOrEmpty(_selectionQuote)) return;

        _selectionSaveCts?.Cancel();
        _selectionSaveCts = new CancellationTokenSource();
        var ct = _selectionSaveCts.Token;
        if (_selectionSaveButton is not null)
            _selectionSaveButton.IsEnabled = false;
        if (_selectionIdeaError is not null)
            _selectionIdeaError.Visibility = Visibility.Collapsed;
        try
        {
            await App.Core.CreateNoteAsync(
                _bookId,
                content,
                _selected.Id,
                quote: _selectionQuote,
                type: "manual",
                ct: ct);
            DismissSelectionFlyout();
            await ReloadNotesAsync();
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            if (_selectionSaveButton is not null)
                _selectionSaveButton.IsEnabled = true;
            if (_selectionIdeaError is not null)
            {
                _selectionIdeaError.Text = ex.Message;
                _selectionIdeaError.Visibility = Visibility.Visible;
            }
        }
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
            assistant.ApplyMetrics(resp);
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
        var choice = await ExportMarkdownDialog.ShowAsync(XamlRoot);
        if (choice is null) return;
        try
        {
            var md = await App.Core.ExportMarkdownAsync(_bookId, choice.Value.IncludeNotes, choice.Value.Mode);
            var window = MainWindowLocator.Current;
            if (window is null) return;
            var picker = new FileSavePicker();
            InitializeWithWindow.Initialize(picker, WindowNative.GetWindowHandle(window));
            picker.SuggestedFileName = ExportMarkdownMode.DefaultFilename(TitleText.Text, choice.Value.Mode);
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
        foreach (var ext in LibraryImportPolicy.Extensions)
            picker.FileTypeFilter.Add(ext);

        var files = await picker.PickMultipleFilesAsync();
        if (files is null || files.Count == 0) return;

        ProgressText.Text = $"导入中…（{files.Count} 个文件，可继续阅读）";
        ProgressBanner.Visibility = Visibility.Visible;
        var skipRemainingDuplicates = false;
        for (var i = 0; i < files.Count; i++)
        {
            var file = files[i];
            var remaining = files.Count - i - 1;
            try
            {
                await App.Core.ImportBookAsync(file.Path);
            }
            catch (ImportConflictException ex)
            {
                if (!ImportConflictPolicy.ShouldPrompt(skipRemainingDuplicates))
                    continue;
                var choice = await ImportConflictDialog.AskAsync(
                    XamlRoot, ex.BookTitle, remaining);
                var decision = ImportConflictPolicy.Decide(choice);
                if (decision.OverwriteCurrent)
                    await App.Core.ImportBookAsync(ex.Path, overwrite: true);
                if (decision.SkipRemainingDuplicates)
                    skipRemainingDuplicates = true;
                if (decision.OpenExisting && !string.IsNullOrEmpty(ex.ExistingBookId))
                    MainWindowLocator.Current?.NavigateToReader(ex.ExistingBookId, ex.BookTitle);
                if (!decision.ContinueQueue)
                    break;
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
        _listen.Stop();
        PersistReadingProgress(patchServer: true);
        _pageCts?.Cancel();
        MainWindowLocator.Current?.NavigateToLibrary();
    }

    private void Listen_Click(object sender, RoutedEventArgs e)
    {
        var showingOriginal = ListenChromePolicy.IsShowingOriginal(_showRaw, _showRaw, false);
        StartListening(ListenChromePolicy.PrimaryMode(showingOriginal));
    }

    private void ListenMode_Click(object sender, RoutedEventArgs e)
    {
        if (sender is MenuFlyoutItem item)
            StartListening(ListenScriptBuilder.ParseMode(item.Tag as string));
    }

    private void StartListening(ListenMode mode)
    {
        if (string.IsNullOrEmpty(_bookId) || _segments.Count == 0) return;
        _listen.Configure(
            _bookId,
            _segments.Count,
            ResolveListenScriptAsync,
            idx => _segments.FirstOrDefault(s => s.Idx == idx)?.DisplayLabel ?? $"段 {idx + 1}",
            () => new SystemNeuralEngine());
        var start = _selected?.Idx ?? _segments[0].Idx;
        _listen.Start(mode, start);
        UpdateListenBar();
    }

    private async Task<ListenScript> ResolveListenScriptAsync(int idx, ListenMode mode, CancellationToken ct)
    {
        if (mode is ListenMode.Summary or ListenMode.Detailed)
        {
            var row = _segments.FirstOrDefault(s => s.Idx == idx);
            var json = row?.SummaryJson;
            if (string.IsNullOrEmpty(json) && _hydrated.TryGetValue(idx, out var cached))
                json = cached.SummaryJson;
            var status = row?.SummaryStatus ?? "";
            if (string.IsNullOrEmpty(json) && status is "ready" or "done")
            {
                var sum = await App.Core.FetchSegmentSummaryAsync(_bookId, idx, ct).ConfigureAwait(true);
                json = sum.SummaryJson;
                if (row is not null) row.SummaryJson = json;
                if (_hydrated.TryGetValue(idx, out var hyd)) hyd.SummaryJson = json;
            }
            return ListenScriptBuilder.Build(mode, json, null);
        }

        if (_hydrated.TryGetValue(idx, out var source) && !string.IsNullOrEmpty(source.RawText))
            return ListenScriptBuilder.Build(ListenMode.Original, null, source.RawText);
        var detail = await App.Core.GetSegmentAsync(_bookId, idx, ct).ConfigureAwait(true);
        _hydrated[idx] = detail;
        return ListenScriptBuilder.Build(ListenMode.Original, null, detail.RawText);
    }

    private void ListenPause_Click(object sender, RoutedEventArgs e) => _listen.TogglePause();
    private void ListenBack_Click(object sender, RoutedEventArgs e) => _listen.SkipBack();
    private void ListenForward_Click(object sender, RoutedEventArgs e) => _listen.SkipForward();
    private void ListenStop_Click(object sender, RoutedEventArgs e) => _listen.Stop();

    private void ListenRate_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (_listenRateSuppress || ListenRateBox is null) return;
        var tag = (ListenRateBox.SelectedItem as ComboBoxItem)?.Tag as string;
        if (!float.TryParse(tag, NumberStyles.Float, CultureInfo.InvariantCulture, out var rate)) return;
        _listen.SetRate(rate);
    }

    private void UpdateListenMenu()
    {
        if (ListenSummaryItem is null) return;
        var showingOriginal = ListenChromePolicy.IsShowingOriginal(_showRaw, _showRaw, false);
        var showChevron = ListenChromePolicy.ShowsSummaryChevron(showingOriginal);
        ListenSummaryItem.Visibility = showChevron ? Visibility.Visible : Visibility.Collapsed;
        ListenDetailedItem.Visibility = showChevron ? Visibility.Visible : Visibility.Collapsed;
        ListenOriginalItem.Visibility = showingOriginal ? Visibility.Visible : Visibility.Collapsed;
        ToolTipService.SetToolTip(ListenSplit, showingOriginal ? "听原文" : "单击听简要摘要；点箭头可选听完整摘要");
    }

    private void UpdateListenBar()
    {
        if (ListenMiniBar is null) return;
        ListenMiniBar.Visibility = _listen.IsActive ? Visibility.Visible : Visibility.Collapsed;
        ListenTitleText.Text = _listen.Title;
        ListenBannerText.Text = _listen.Banner;
        ListenBannerText.Visibility = string.IsNullOrEmpty(_listen.Banner) ? Visibility.Collapsed : Visibility.Visible;
        ListenPauseBtn.Content = _listen.IsPaused || !_listen.IsPlaying ? "继续" : "暂停";
        ListenPauseBtn.IsEnabled = _listen.IsActive;
        ListenBackBtn.IsEnabled = _listen.IsActive;
        ListenForwardBtn.IsEnabled = _listen.IsActive;
        var wanted = RateTag(_listen.Rate);
        _listenRateSuppress = true;
        foreach (var item in ListenRateBox.Items.OfType<ComboBoxItem>())
        {
            if (item.Tag as string == wanted)
            {
                ListenRateBox.SelectedItem = item;
                break;
            }
        }
        _listenRateSuppress = false;
    }

    private static string RateTag(float rate)
    {
        var snapped = ListenPreferences.SnapRate(rate);
        if (Math.Abs(snapped - 1.0f) < 0.01) return "1";
        if (Math.Abs(snapped - 2.0f) < 0.01) return "2";
        return snapped.ToString("0.##", CultureInfo.InvariantCulture);
    }
}
