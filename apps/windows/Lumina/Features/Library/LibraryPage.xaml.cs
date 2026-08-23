using Lumina.Features.Notes;
using Lumina.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;
using Windows.Storage.Pickers;
using WinRT.Interop;

namespace Lumina.Features.Library;

public sealed partial class LibraryPage : Page
{
    private CancellationTokenSource? _loadCts;
    private List<BookSummary> _allBooks = [];
    private string _collection = LibraryCollections.Recent;
    private string _sort = LibrarySorts.Recent;
    private string _titleQuery = "";
    private bool _gridMode = true;
    private bool _suppressFilter;

    public LibraryPage()
    {
        InitializeComponent();
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        _ = ReloadAsync();
    }

    protected override void OnNavigatedFrom(NavigationEventArgs e)
    {
        _loadCts?.Cancel();
        base.OnNavigatedFrom(e);
    }

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
            _suppressFilter = false;

            _allBooks = booksTask.Result.ToList();
            ApplyLocalFilters();
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

    private void RebuildCollections(IReadOnlyList<string> categories)
    {
        var selected = _collection;
        CollectionNav.MenuItems.Clear();
        AddNavItem("最近", LibraryCollections.Recent);
        CollectionNav.MenuItems.Add(new NavigationViewItemHeader { Content = "摘要" });
        AddNavItem("未摘要", LibraryCollections.Idle);
        AddNavItem("摘要中", LibraryCollections.Summarizing);
        AddNavItem("已摘要", LibraryCollections.Summarized);
        CollectionNav.MenuItems.Add(new NavigationViewItemHeader { Content = "阅读" });
        AddNavItem("未读", LibraryCollections.Unread);
        AddNavItem("在读", LibraryCollections.Reading);
        AddNavItem("已读完", LibraryCollections.Finished);
        AddNavItem("收藏", LibraryCollections.Favorite);
        CollectionNav.MenuItems.Add(new NavigationViewItemHeader { Content = "分类" });
        foreach (var c in categories.Concat(LibraryCollections.FallbackCategories).Distinct())
            AddNavItem(c, c);

        foreach (var item in CollectionNav.MenuItems.OfType<NavigationViewItem>())
        {
            if (item.Tag as string == selected)
            {
                CollectionNav.SelectedItem = item;
                return;
            }
        }
        CollectionNav.SelectedItem = CollectionNav.MenuItems.OfType<NavigationViewItem>().FirstOrDefault();
    }

    private void AddNavItem(string content, string tag)
    {
        var count = _allBooks.Count(b => LibraryCollections.Matches(tag, b));
        CollectionNav.MenuItems.Add(new NavigationViewItem
        {
            Content = count > 0 ? $"{content}  {count}" : content,
            Tag = tag,
        });
    }

    private void ApplyLocalFilters()
    {
        IEnumerable<BookSummary> q = _allBooks.Where(b => LibraryCollections.Matches(_collection, b));
        if (!string.IsNullOrWhiteSpace(_titleQuery))
            q = q.Where(b => b.Title.Contains(_titleQuery, StringComparison.CurrentCultureIgnoreCase));
        var list = LibrarySorts.Sorted(q, _sort);
        if (_collection == LibraryCollections.Recent && _sort == LibrarySorts.Recent)
        {
            list = list
                .OrderBy(b => b.SummarizeState == "running" ? 0 : b.SummarizeState == "queued" ? 1 : 2)
                .ThenBy(b => b.LastOpenedAt is null)
                .ThenByDescending(b => b.LastOpenedAt ?? "")
                .ToList();
        }
        BooksList.ItemsSource = list;
        BooksGrid.ItemsSource = list;
        TitleText.Text = LibraryCollections.Label(_collection);
        StatusText.Text = list.Count == 0 ? "暂无书籍，点击「导入」开始" : $"共 {list.Count} 本";
        UpdateBatchBar();
        RefreshNavCounts();
    }

    private void RefreshNavCounts()
    {
        foreach (var item in CollectionNav.MenuItems.OfType<NavigationViewItem>())
        {
            if (item.Tag is not string tag) continue;
            var label = LibraryCollections.Label(tag);
            var count = _allBooks.Count(b => LibraryCollections.Matches(tag, b));
            item.Content = count > 0 ? $"{label}  {count}" : label;
        }
    }

    private void CollectionNav_SelectionChanged(
        NavigationView sender,
        NavigationViewSelectionChangedEventArgs args)
    {
        if (_suppressFilter) return;
        if (args.SelectedItem is not NavigationViewItem { Tag: string tag }) return;
        _collection = tag;
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

    private async void Import_Click(object sender, RoutedEventArgs e)
    {
        var window = MainWindowLocator.Current;
        if (window is null)
        {
            StatusText.Text = "窗口未就绪";
            return;
        }

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

        StatusText.Text = $"导入中…（{files.Count} 个文件，可继续浏览）";
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
                StatusText.Text = $"导入失败：{ex.Message}";
            }
        }
        await ReloadAsync();
    }

    private void BooksList_ItemClick(object sender, ItemClickEventArgs e)
    {
        if (e.ClickedItem is not BookSummary book) return;
        if (ActiveList().SelectedItems.Count > 1) return;
        if (book.Status is "processing" or "error")
        {
            StatusText.Text = book.Status == "processing"
                ? "正在后台解析，可继续使用书库；删除该书即可取消"
                : string.IsNullOrWhiteSpace(book.IngestError)
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

    private async void BatchSummarize_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var tier = BatchSummaryTierBox.SelectedItem is ComboBoxItem { Tag: "advanced" }
                ? SummaryTier.Advanced
                : SummaryTier.Normal;
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
        classify.Click += async (_, _) =>
        {
            try
            {
                await App.Core.ClassifyBookAsync(id);
                StatusText.Text = "已请求分类";
                await ReloadAsync();
            }
            catch (Exception ex) { StatusText.Text = ex.Message; }
        };

        var export = new MenuFlyoutItem { Text = "导出 Markdown" };
        export.IsEnabled = book.HasExportableSummary;
        export.Click += async (_, _) =>
        {
            try
            {
                var md = await App.Core.ExportMarkdownAsync(id, includeNotes: true);
                var picker = new FileSavePicker();
                var window = MainWindowLocator.Current;
                if (window is null) return;
                InitializeWithWindow.Initialize(picker, WindowNative.GetWindowHandle(window));
                picker.SuggestedFileName = $"{book.Title}.md";
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
        flyout.Items.Add(export);
        flyout.Items.Add(delete);
        flyout.ShowAt(sender as FrameworkElement);
    }
}
