using Lumina.Design;
using Lumina.Features.Notes;
using Lumina.Features.Shared;
using Lumina.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;
using WinRT.Interop;
using System.Text.Json;

namespace Lumina.Features.Library;

public sealed partial class LibraryPage : Page
{
    private CancellationTokenSource? _loadCts;
    private CancellationTokenSource? _overviewCts;
    private DispatcherTimer? _overviewTimer;
    private List<BookSummary> _allBooks = [];
    private List<BookSummary> _visibleBooks = [];
    private string _summary = LibraryFacets.All;
    private string _reading = LibraryFacets.All;
    private string _category = LibraryFacets.All;
    private bool _favoriteOnly;
    private string _sort = LibrarySorts.Recent;
    private string _titleQuery = "";
    private bool _gridMode = true;
    private bool _suppressFilter;
    private bool _pendingImport;
    private readonly Dictionary<string, CancellationTokenSource> _ingestEvents = [];
    private readonly HashSet<string> _classifyingIds = [];

    public LibraryPage()
    {
        InitializeComponent();
        _summary = LocalPrefs.LibrarySummary;
        _reading = LocalPrefs.LibraryReading;
        _category = LocalPrefs.LibraryCategory;
        _favoriteOnly = LocalPrefs.LibraryFavoriteOnly;
        _sort = LocalPrefs.LibrarySort;
        _gridMode = LocalPrefs.LibraryGridMode;
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        _pendingImport = e.Parameter is LibraryNavArgs { OpenImport: true };
        StartOverviewPolling();
        _ = ReloadThenMaybeImportAsync();
    }

    protected override void OnNavigatedFrom(NavigationEventArgs e)
    {
        _loadCts?.Cancel();
        _overviewCts?.Cancel();
        _overviewTimer?.Stop();
        StopIngestSubscriptions();
        base.OnNavigatedFrom(e);
    }

    private async Task ReloadThenMaybeImportAsync()
    {
        await ReloadAsync();
        if (!_pendingImport) return;
        _pendingImport = false;
        await BeginImportAsync();
    }

    public Task BeginImportAsync() => BeginImportAsync(null);

    private async void Refresh_Click(object sender, RoutedEventArgs e) => await ReloadAsync();

    private void AllNotes_Click(object sender, RoutedEventArgs e)
    {
        Frame.Navigate(typeof(AllNotesPage));
    }

    private async Task ReloadAsync()
    {
        _loadCts?.Cancel();
        _loadCts = new CancellationTokenSource();
        var ct = _loadCts.Token;

        LoadingRing.IsActive = true;
        StatusText.Text = "加载书库…";
        try
        {
            if (!App.Sidecar.IsRunning)
            {
                if (App.Sidecar.UserStopped)
                {
                    StatusText.Text = "引擎已停止";
                    BooksList.ItemsSource = null;
                    BooksGrid.ItemsSource = null;
                    return;
                }
                await App.Sidecar.EnsureRunningAsync(ct);
                if (!App.Sidecar.IsRunning)
                {
                    StatusText.Text = App.Sidecar.LaunchError ?? "引擎未就绪";
                    BooksList.ItemsSource = null;
                    BooksGrid.ItemsSource = null;
                    return;
                }
            }

            var catsTask = App.Core.ListBookCategoriesAsync(ct);
            var booksTask = App.Core.ListBooksAsync(LibraryFilters.All, _sort, ct);
            await Task.WhenAll(catsTask, booksTask);
            ct.ThrowIfCancellationRequested();

            _suppressFilter = true;
            RebuildCollections(catsTask.Result);
            SelectCombo(SortBox, _sort);
            SelectCombo(ViewModeBox, _gridMode ? "grid" : "list");
            BooksGrid.Visibility = _gridMode ? Visibility.Visible : Visibility.Collapsed;
            BooksList.Visibility = _gridMode ? Visibility.Collapsed : Visibility.Visible;
            _suppressFilter = false;

            var previous = _allBooks.ToDictionary(b => b.Id);
            _allBooks = OverlayLocalProgress(booksTask.Result);
            foreach (var book in _allBooks)
            {
                if (!previous.TryGetValue(book.Id, out var old)) continue;
                book.IngestMessage = old.IngestMessage;
                book.IngestPage = old.IngestPage;
                book.IngestTotal = old.IngestTotal;
            }
            ApplyLocalFilters();
            SyncIngestSubscriptions();
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            StatusText.Text = ex.Message;
        }
        finally
        {
            LoadingRing.IsActive = false;
        }
    }

    static List<BookSummary> OverlayLocalProgress(IReadOnlyList<BookSummary> books)
    {
        var list = books.ToList();
        foreach (var book in list)
        {
            if (LocalPrefs.GetCachedProgress(book.Id) is not { } cached) continue;
            ReadingProgressIndex.OverlayLocal(book, cached.Index, cached.SegmentCount, cached.Percent);
        }
        return list;
    }

    private void RebuildCollections(IReadOnlyList<string> categories)
    {
        FilterPane.Children.Clear();
        AddHeader("摘要");
        AddRadio(LibraryFacets.SummaryGroup, "全部", LibraryFacets.All, _summary);
        AddRadio(LibraryFacets.SummaryGroup, "未摘要", LibraryCollections.Idle, _summary);
        AddRadio(LibraryFacets.SummaryGroup, "分段中", LibraryCollections.Segmenting, _summary);
        AddRadio(LibraryFacets.SummaryGroup, "摘要中", LibraryCollections.Summarizing, _summary);
        AddRadio(LibraryFacets.SummaryGroup, "已摘要", LibraryCollections.Summarized, _summary);
        AddRadio(LibraryFacets.SummaryGroup, "导入失败", LibraryCollections.IngestFailed, _summary);

        AddHeader("阅读");
        AddRadio(LibraryFacets.ReadingGroup, "全部", LibraryFacets.All, _reading);
        AddRadio(LibraryFacets.ReadingGroup, "未读", LibraryCollections.Unread, _reading);
        AddRadio(LibraryFacets.ReadingGroup, "在读", LibraryCollections.Reading, _reading);
        AddRadio(LibraryFacets.ReadingGroup, "已读完", LibraryCollections.Finished, _reading);

        var favorite = new CheckBox
        {
            Content = "收藏",
            Tag = LibraryCollections.Favorite,
            IsChecked = _favoriteOnly,
            Margin = new Thickness(0, 12, 0, 4),
        };
        favorite.Checked += FavoriteFilter_Changed;
        favorite.Unchecked += FavoriteFilter_Changed;
        FilterPane.Children.Add(favorite);

        AddHeader("分类");
        AddRadio(LibraryFacets.CategoryGroup, "全部", LibraryFacets.All, _category);
        foreach (var c in categories.Concat(LibraryCollections.FallbackCategories).Distinct())
            AddRadio(LibraryFacets.CategoryGroup, c, c, _category);
        if (!LibraryFacets.IsAll(_category)
            && FilterPane.Children.OfType<RadioButton>().All(r =>
                r.GroupName != LibraryFacets.CategoryGroup || r.Tag as string != _category))
        {
            AddRadio(LibraryFacets.CategoryGroup, _category, _category, _category);
        }
    }

    private void AddHeader(string text)
    {
        FilterPane.Children.Add(new TextBlock
        {
            Text = text,
            FontWeight = Windows.UI.Text.FontWeights.SemiBold,
            Margin = new Thickness(0, FilterPane.Children.Count == 0 ? 0 : 16, 0, 6),
        });
    }

    private void AddRadio(string group, string content, string tag, string selected)
    {
        var radio = new RadioButton
        {
            GroupName = group,
            Content = content,
            Tag = tag,
            IsChecked = tag == selected,
            MinHeight = 32,
        };
        radio.Checked += FilterRadio_Checked;
        FilterPane.Children.Add(radio);
    }

    private void ApplyLocalFilters()
    {
        IEnumerable<BookSummary> q = _allBooks.Where(b =>
            LibraryFacets.Matches(b, _summary, _reading, _category, _favoriteOnly));
        if (!string.IsNullOrWhiteSpace(_titleQuery))
            q = q.Where(b => b.Title.Contains(_titleQuery, StringComparison.CurrentCultureIgnoreCase));
        var list = LibrarySorts.Sorted(q, _sort).ToList();
        if (LibraryFacets.IsDefault(_summary, _reading, _category, _favoriteOnly)
            && _sort == LibrarySorts.Recent)
        {
            list = list
                .OrderBy(b => b.SummarizeState == "running" ? 0 : b.SummarizeState == "queued" ? 1 : 2)
                .ThenBy(b => b.LastOpenedAt is null)
                .ThenByDescending(b => b.LastOpenedAt ?? "")
                .ToList();
        }
        BooksList.ItemsSource = null;
        BooksGrid.ItemsSource = null;
        BooksList.ItemsSource = list;
        BooksGrid.ItemsSource = list;
        _visibleBooks = list;
        TitleText.Text = LibraryFacets.Title(_summary, _reading, _category, _favoriteOnly);
        StatusText.Text = _allBooks.Count == 0
            ? "暂无书籍，点击「导入」开始"
            : list.Count == 0
                ? "没有符合筛选的书"
                : $"共 {list.Count} 本";
        UpdateBatchBar();
        RefreshFilterCounts();
        PersistLibraryPrefs();
    }

    private void PersistLibraryPrefs()
    {
        LocalPrefs.LibrarySummary = _summary;
        LocalPrefs.LibraryReading = _reading;
        LocalPrefs.LibraryCategory = _category;
        LocalPrefs.LibraryFavoriteOnly = _favoriteOnly;
        LocalPrefs.LibrarySort = _sort;
        LocalPrefs.LibraryGridMode = _gridMode;
    }

    private void RefreshFilterCounts()
    {
        foreach (var radio in FilterPane.Children.OfType<RadioButton>())
        {
            if (radio.Tag is not string tag || radio.GroupName is not string group) continue;
            var label = LibraryFacets.IsAll(tag) ? "全部" : LibraryCollections.Label(tag);
            var count = _allBooks.Count(b => LibraryFacets.MatchesProjected(
                b, group, tag, _summary, _reading, _category, _favoriteOnly));
            radio.Content = count > 0 ? $"{label}  {count}" : label;
        }
        if (FilterPane.Children.OfType<CheckBox>().FirstOrDefault() is { } favorite)
        {
            var count = _allBooks.Count(b => LibraryFacets.MatchesProjected(
                b, LibraryCollections.Favorite, LibraryCollections.Favorite,
                _summary, _reading, _category, _favoriteOnly));
            favorite.Content = count > 0 ? $"收藏  {count}" : "收藏";
        }
    }

    private void StopIngestSubscriptions()
    {
        foreach (var cts in _ingestEvents.Values)
            cts.Cancel();
        _ingestEvents.Clear();
    }

    private void SyncIngestSubscriptions()
    {
        var processing = _allBooks.Where(b => b.Status == "processing").Select(b => b.Id).ToHashSet();
        foreach (var id in _ingestEvents.Keys.ToList())
        {
            if (processing.Contains(id)) continue;
            _ingestEvents[id].Cancel();
            _ingestEvents.Remove(id);
        }
        foreach (var book in _allBooks.Where(b => b.Status == "processing"))
        {
            if (_ingestEvents.ContainsKey(book.Id)) continue;
            if (book.ProcessingKind == "resegment" && string.IsNullOrWhiteSpace(book.IngestMessage))
                book.IngestMessage = "正在重新分段…";
            var bookId = book.Id;
            _ingestEvents[bookId] = App.Core.SubscribeEvents(bookId, el =>
            {
                DispatcherQueue.TryEnqueue(() => HandleIngestEvent(bookId, el));
            });
        }
    }

    private void HandleIngestEvent(string bookId, JsonElement el)
    {
        if (!el.TryGetProperty("type", out var typeEl)) return;
        var type = typeEl.GetString();
        var book = _allBooks.FirstOrDefault(b => b.Id == bookId);
        switch (type)
        {
            case "resegment_started":
                if (book is null) return;
                book.IngestMessage = "正在重新分段…";
                book.IngestPage = 0;
                book.IngestTotal = 0;
                ApplyLocalFilters();
                break;
            case "ingest_progress":
                if (book is null) return;
                book.IngestPage = el.TryGetProperty("page", out var pageEl) && pageEl.TryGetInt32(out var page)
                    ? page : 0;
                book.IngestTotal = el.TryGetProperty("total", out var totalEl) && totalEl.TryGetInt32(out var total)
                    ? total : 0;
                book.IngestMessage = el.TryGetProperty("message", out var msgEl)
                    ? msgEl.GetString() ?? ""
                    : "";
                ApplyLocalFilters();
                break;
            case "ingest_complete":
            case "ingest_failed":
            case "ingest_cancelled":
            case "resegment_failed":
            case "resegment_cancelled":
                if (_ingestEvents.Remove(bookId, out var cts))
                    cts.Cancel();
                _ = ReloadAsync();
                break;
        }
    }

    private void FilterRadio_Checked(object sender, RoutedEventArgs e)
    {
        if (_suppressFilter) return;
        if (sender is not RadioButton { Tag: string tag, GroupName: string group }) return;
        switch (group)
        {
            case LibraryFacets.SummaryGroup: _summary = tag; break;
            case LibraryFacets.ReadingGroup: _reading = tag; break;
            case LibraryFacets.CategoryGroup: _category = tag; break;
            default: return;
        }
        ApplyLocalFilters();
    }

    private void FavoriteFilter_Changed(object sender, RoutedEventArgs e)
    {
        if (_suppressFilter) return;
        _favoriteOnly = (sender as CheckBox)?.IsChecked == true;
        ApplyLocalFilters();
    }

    private void TitleFilter_Changed(object sender, TextChangedEventArgs e)
    {
        _titleQuery = TitleFilterBox.Text?.Trim() ?? "";
        ApplyLocalFilters();
    }

    private void ViewMode_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (_suppressFilter) return;
        _gridMode = (ViewModeBox.SelectedItem as ComboBoxItem)?.Tag as string != "list";
        BooksGrid.Visibility = _gridMode ? Visibility.Visible : Visibility.Collapsed;
        BooksList.Visibility = _gridMode ? Visibility.Collapsed : Visibility.Visible;
        PersistLibraryPrefs();
    }

    private async void Filter_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (_suppressFilter) return;
        var newSort = (SortBox.SelectedItem as ComboBoxItem)?.Tag as string ?? LibrarySorts.Recent;
        if (newSort != _sort)
        {
            _sort = newSort;
            await ReloadAsync();
            return;
        }
        ApplyLocalFilters();
    }

    private static void SelectCombo(ComboBox box, string tag)
    {
        foreach (var item in box.Items.OfType<ComboBoxItem>())
        {
            if (item.Tag as string == tag)
            {
                box.SelectedItem = item;
                return;
            }
        }
    }

    private async void Import_Click(object sender, RoutedEventArgs e) => await BeginImportAsync();

    public async Task BeginImportAsync(IReadOnlyList<string>? paths)
    {
        IReadOnlyList<string> files;
        if (paths is { Count: > 0 })
        {
            files = paths;
        }
        else
        {
            var window = MainWindowLocator.Current;
            if (window is null)
            {
                StatusText.Text = "窗口未就绪";
                return;
            }

            var picker = new FileOpenPicker();
            InitializeWithWindow.Initialize(picker, WindowNative.GetWindowHandle(window));
            foreach (var ext in LibraryImportPolicy.Extensions)
                picker.FileTypeFilter.Add(ext);

            var picked = await picker.PickMultipleFilesAsync();
            if (picked is null || picked.Count == 0) return;
            files = picked.Select(f => f.Path).ToList();
        }

        StatusText.Text = $"导入中…（{files.Count} 个文件，可继续浏览）";
        var skipRemainingDuplicates = false;
        for (var i = 0; i < files.Count; i++)
        {
            var path = files[i];
            var remaining = files.Count - i - 1;
            try
            {
                await App.Core.ImportBookAsync(path);
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
                StatusText.Text = $"导入失败：{ex.Message}";
            }
        }
        await ReloadAsync();
    }

    private void Books_DragOver(object sender, DragEventArgs e)
    {
        if (e.DataView.Contains(StandardDataFormats.StorageItems))
            e.AcceptedOperation = DataPackageOperation.Copy;
    }

    private async void Books_Drop(object sender, DragEventArgs e)
    {
        if (!e.DataView.Contains(StandardDataFormats.StorageItems)) return;
        IReadOnlyList<IStorageItem> items;
        try
        {
            items = await e.DataView.GetStorageItemsAsync();
        }
        catch
        {
            return;
        }
        var filePaths = items.OfType<StorageFile>().Select(f => f.Path).ToList();
        var folderPaths = items.OfType<StorageFolder>().Select(f => f.Path).ToList();
        var paths = await Task.Run(() =>
            LibraryImportPolicy.CollectImportPaths(filePaths, folderPaths));
        if (paths.Count == 0)
        {
            StatusText.Text = "没有可导入的文件";
            return;
        }
        await BeginImportAsync(paths);
    }

    private void BooksList_ItemClick(object sender, ItemClickEventArgs e)
    {
        if (e.ClickedItem is not BookSummary book) return;
        if (ActiveList().SelectedItems.Count > 1) return;
        if (!book.CanOpenInReader)
        {
            StatusText.Text = string.IsNullOrWhiteSpace(book.IngestError)
                ? "导入失败，请删除后重试"
                : $"导入失败：{book.IngestError}";
            return;
        }
        MainWindowLocator.Current?.NavigateToReader(book.Id, book.Title);
    }

    private void BooksList_SelectionChanged(object sender, SelectionChangedEventArgs e) => UpdateBatchBar();

    private void UpdateBatchBar()
    {
        var n = ActiveList().SelectedItems.Count;
        BatchBar.Visibility = n > 0 ? Visibility.Visible : Visibility.Collapsed;
        BatchCountText.Text = $"已选 {n} 本";
        if (LibraryStartSummarizeSplit is not null)
            LibraryStartSummarizeSplit.Visibility = n > 0 ? Visibility.Collapsed : Visibility.Visible;
        if (n > 0) StatusText.Text = "";
    }

    private ListViewBase ActiveList() => _gridMode ? BooksGrid : BooksList;

    private List<string> SelectedIds() =>
        ActiveList().SelectedItems.OfType<BookSummary>().Select(b => b.Id).ToList();

    private async void BatchFavorite_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            await App.Core.SetBooksFavoriteAsync(SelectedIds(), true);
            await ReloadAsync();
        }
        catch (Exception ex) { StatusText.Text = ex.Message; }
    }

    private async void BatchUnfavorite_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            await App.Core.SetBooksFavoriteAsync(SelectedIds(), false);
            await ReloadAsync();
        }
        catch (Exception ex) { StatusText.Text = ex.Message; }
    }

    private async void BatchSummarize_Click(object sender, RoutedEventArgs e) =>
        await StartBatchSummarizeAsync(SummaryTier.Normal);

    private async void BatchSummarizeAdvanced_Click(object sender, RoutedEventArgs e)
    {
        BatchStartSummarizeSplit.Flyout?.Hide();
        if (!await ConfirmAdvancedStartAsync()) return;
        await StartBatchSummarizeAsync(SummaryTier.Advanced);
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

    private async Task StartBatchSummarizeAsync(SummaryTier tier)
    {
        try
        {
            await App.Core.StartSummarizeBooksAsync(SelectedIds(), tier);
            StatusText.Text = "已开始摘要";
            await ReloadAsync();
        }
        catch (Exception ex) { StatusText.Text = ex.Message; }
    }

    private async void BatchStop_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            await App.Core.StopSummarizeBooksAsync(SelectedIds());
            StatusText.Text = "已请求停止";
            await ReloadAsync();
        }
        catch (Exception ex) { StatusText.Text = ex.Message; }
    }

    private async void BatchDelete_Click(object sender, RoutedEventArgs e)
    {
        var ids = SelectedIds();
        var dlg = new ContentDialog
        {
            Title = "删除书籍",
            Content = $"确定删除选中的 {ids.Count} 本书？此操作不可撤销。",
            PrimaryButtonText = "删除",
            CloseButtonText = "取消",
            XamlRoot = XamlRoot,
        };
        if (await dlg.ShowAsync() != ContentDialogResult.Primary) return;
        try
        {
            await App.Core.DeleteBooksAsync(ids);
            await ReloadAsync();
        }
        catch (Exception ex) { StatusText.Text = ex.Message; }
    }

    private void ClearSelection_Click(object sender, RoutedEventArgs e)
    {
        BooksList.SelectedItems.Clear();
        BooksGrid.SelectedItems.Clear();
    }

    private async void Favorite_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button { Tag: string id }) return;
        var book = _allBooks.FirstOrDefault(b => b.Id == id);
        if (book is null) return;
        try
        {
            await App.Core.UpdateBookAsync(id, isFavorite: !book.Favorite);
            await ReloadAsync();
        }
        catch (Exception ex) { StatusText.Text = ex.Message; }
    }

    private async void More_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button { Tag: string id }) return;
        var book = _allBooks.FirstOrDefault(b => b.Id == id);
        if (book is null) return;

        var rename = new MenuFlyoutItem { Text = "重命名" };
        rename.Click += async (_, _) =>
        {
            var box = new TextBox { Text = book.Title };
            var dlg = new ContentDialog
            {
                Title = "重命名",
                Content = box,
                PrimaryButtonText = "保存",
                CloseButtonText = "取消",
                XamlRoot = XamlRoot,
            };
            if (await dlg.ShowAsync() == ContentDialogResult.Primary && !string.IsNullOrWhiteSpace(box.Text))
            {
                await App.Core.UpdateBookAsync(id, title: box.Text.Trim());
                await ReloadAsync();
            }
        };

        var category = new MenuFlyoutItem { Text = "改分类" };
        category.Click += async (_, _) =>
        {
            var box = new TextBox { Text = book.Category ?? "", PlaceholderText = "如：科技" };
            var dlg = new ContentDialog
            {
                Title = "改分类",
                Content = box,
                PrimaryButtonText = "保存",
                CloseButtonText = "取消",
                XamlRoot = XamlRoot,
            };
            if (await dlg.ShowAsync() == ContentDialogResult.Primary)
            {
                await App.Core.UpdateBookAsync(id, category: box.Text.Trim());
                await ReloadAsync();
            }
        };

        var classify = new MenuFlyoutItem { Text = "AI 分类" };
        classify.IsEnabled = !_classifyingIds.Contains(id);
        classify.Click += async (_, _) =>
        {
            if (!_classifyingIds.Add(id)) return;
            try
            {
                await App.Core.ClassifyBookAsync(id);
                StatusText.Text = "已请求分类";
                await ReloadAsync();
            }
            catch (Exception ex) { StatusText.Text = ex.Message; }
            finally { _classifyingIds.Remove(id); }
        };

        var resegment = new MenuFlyoutItem { Text = "整书重新分段" };
        resegment.IsEnabled = book.CanResegment;
        resegment.Click += async (_, _) => await ConfirmResegmentAsync(book);

        var cancelIngest = new MenuFlyoutItem { Text = "取消导入" };
        cancelIngest.Visibility = book.CanCancelIngest ? Visibility.Visible : Visibility.Collapsed;
        cancelIngest.Click += async (_, _) => await CancelBookWorkAsync(book, resegment: false);

        var cancelResegment = new MenuFlyoutItem { Text = "取消重新分段" };
        cancelResegment.Visibility = book.CanCancelResegment ? Visibility.Visible : Visibility.Collapsed;
        cancelResegment.Click += async (_, _) => await CancelBookWorkAsync(book, resegment: true);

        var export = new MenuFlyoutItem { Text = "导出 Markdown" };
        export.IsEnabled = book.HasExportableSummary;
        export.Click += async (_, _) =>
        {
            var choice = await ExportMarkdownDialog.ShowAsync(XamlRoot);
            if (choice is null) return;
            try
            {
                var md = await App.Core.ExportMarkdownAsync(id, choice.Value.IncludeNotes, choice.Value.Mode);
                var picker = new FileSavePicker();
                var window = MainWindowLocator.Current;
                if (window is null) return;
                InitializeWithWindow.Initialize(picker, WindowNative.GetWindowHandle(window));
                picker.SuggestedFileName = ExportMarkdownMode.DefaultFilename(book.Title, choice.Value.Mode);
                picker.FileTypeChoices.Add("Markdown", [".md"]);
                var file = await picker.PickSaveFileAsync();
                if (file is null) return;
                await File.WriteAllTextAsync(file.Path, md);
                StatusText.Text = "已导出";
            }
            catch (Exception ex) { StatusText.Text = ex.Message; }
        };

        var delete = new MenuFlyoutItem { Text = "删除" };
        delete.Click += async (_, _) =>
        {
            var dlg = new ContentDialog
            {
                Title = "删除书籍",
                Content = $"确定删除「{book.Title}」？",
                PrimaryButtonText = "删除",
                CloseButtonText = "取消",
                XamlRoot = XamlRoot,
            };
            if (await dlg.ShowAsync() != ContentDialogResult.Primary) return;
            await App.Core.DeleteBookAsync(id);
            await ReloadAsync();
        };

        var flyout = new MenuFlyout();
        flyout.Items.Add(rename);
        flyout.Items.Add(category);
        flyout.Items.Add(classify);
        flyout.Items.Add(resegment);
        if (book.CanCancelIngest) flyout.Items.Add(cancelIngest);
        if (book.CanCancelResegment) flyout.Items.Add(cancelResegment);
        flyout.Items.Add(export);
        flyout.Items.Add(delete);
        flyout.ShowAt(sender as FrameworkElement);
    }

    private async Task ConfirmResegmentAsync(BookSummary book)
    {
        var choice = await ResegmentBookDialog.ShowAsync(XamlRoot, book);
        if (choice is null) return;
        try
        {
            LocalPrefs.ClearCachedProgress(book.Id);
            await App.Core.ResegmentBookAsync(book.Id, choice.Value.ChunkTargetChars, choice.Value.Tier);
            StatusText.Text = "正在重新分段…";
            await ReloadAsync();
        }
        catch (Exception ex) { StatusText.Text = ex.Message; }
    }

    private async Task CancelBookWorkAsync(BookSummary book, bool resegment)
    {
        try
        {
            if (resegment)
                await App.Core.CancelResegmentBookAsync(book.Id);
            else
                await App.Core.CancelIngestAsync(book.Id);
            StatusText.Text = resegment ? "已取消重新分段" : "已取消导入";
            await ReloadAsync();
        }
        catch (Exception ex) { StatusText.Text = ex.Message; }
    }

    private void StartOverviewPolling()
    {
        _overviewTimer?.Stop();
        _overviewTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(3) };
        _overviewTimer.Tick += async (_, _) => await RefreshSummarizeActivityAsync();
        _overviewTimer.Start();
        _ = RefreshSummarizeActivityAsync();
    }

    private async Task RefreshSummarizeActivityAsync()
    {
        _overviewCts?.Cancel();
        _overviewCts = new CancellationTokenSource();
        var ct = _overviewCts.Token;
        try
        {
            var overview = await App.Core.FetchSummarizeOverviewAsync(ct);
            if (ct.IsCancellationRequested) return;
            var show = SummarizeActivityPolicy.ShouldShow(overview);
            SummarizeActivityBar.Visibility = show ? Visibility.Visible : Visibility.Collapsed;
            if (show)
                SummarizeActivityStatus.Content = SummarizeActivityPolicy.StatusLabel(overview);
        }
        catch (OperationCanceledException) { }
        catch
        {
            SummarizeActivityBar.Visibility = Visibility.Collapsed;
        }
    }

    private void SummarizeActivity_Click(object sender, RoutedEventArgs e)
    {
        _summary = SummarizeActivityPolicy.DestinationCollection;
        PersistLibraryPrefs();
        foreach (var radio in FilterPane.Children.OfType<RadioButton>())
        {
            if (radio.GroupName == LibraryFacets.SummaryGroup
                && radio.Tag as string == LibraryCollections.Summarizing)
            {
                radio.IsChecked = true;
                break;
            }
        }
        ApplyLocalFilters();
    }

    private async void SummarizeActivityStop_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            await App.Core.StopSummarizeAllAsync();
            StatusText.Text = "已请求停止全部摘要";
            await RefreshSummarizeActivityAsync();
            await ReloadAsync();
        }
        catch (Exception ex) { StatusText.Text = ex.Message; }
    }

    private async void LibrarySummarize_Click(object sender, RoutedEventArgs e) =>
        await StartLibrarySummarizeAsync(SummaryTier.Normal);

    private async void LibrarySummarizeAdvanced_Click(object sender, RoutedEventArgs e)
    {
        LibraryStartSummarizeSplit.Flyout?.Hide();
        if (!await ConfirmAdvancedStartAsync()) return;
        await StartLibrarySummarizeAsync(SummaryTier.Advanced);
    }

    private async Task StartLibrarySummarizeAsync(SummaryTier tier)
    {
        try
        {
            var libraryWide = LibrarySummarizeScope.IsLibraryWide(
                LibraryFacets.IsDefault(_summary, _reading, _category, _favoriteOnly),
                _titleQuery);
            var ids = LibrarySummarizeScope.IdsForUnselectedStart(_visibleBooks, libraryWide);
            if (ids is { Count: 0 })
            {
                StatusText.Text = "当前列表没有可摘要的书";
                return;
            }
            if (ids is null)
                await App.Core.StartSummarizeAllAsync(tier);
            else
                await App.Core.StartSummarizeBooksAsync(ids, tier);
            StatusText.Text = ids is null ? "已开始摘要全书" : $"已开始摘要 {ids.Count} 本";
            await RefreshSummarizeActivityAsync();
            await ReloadAsync();
        }
        catch (Exception ex) { StatusText.Text = ex.Message; }
    }

    private async void LibraryStopSummarize_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            await App.Core.StopSummarizeAllAsync();
            StatusText.Text = "已请求停止";
            await RefreshSummarizeActivityAsync();
            await ReloadAsync();
        }
        catch (Exception ex) { StatusText.Text = ex.Message; }
    }
}
