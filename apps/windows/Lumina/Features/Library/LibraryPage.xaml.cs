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
    private string _categoryFilter = LibraryFilters.All;
    private string _stateFilter = SummarizeStateFilters.All;
    private string _sort = LibrarySorts.Recent;
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
                    return;
                }
            }

            var catsTask = App.Core.ListBookCategoriesAsync(ct);
            var booksTask = App.Core.ListBooksAsync(_categoryFilter, _sort, ct);
            await Task.WhenAll(catsTask, booksTask);
            ct.ThrowIfCancellationRequested();

            _suppressFilter = true;
            var cats = catsTask.Result;
            CategoryBox.Items.Clear();
            CategoryBox.Items.Add(new ComboBoxItem { Content = "全部", Tag = LibraryFilters.All, IsSelected = true });
            foreach (var c in cats.Concat(LibraryFilters.FallbackCategories).Distinct())
                CategoryBox.Items.Add(new ComboBoxItem { Content = c, Tag = c });
            SelectCombo(CategoryBox, _categoryFilter);
            SelectCombo(StateBox, _stateFilter);
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

    private void ApplyLocalFilters()
    {
        IEnumerable<BookSummary> q = _allBooks;
        if (_stateFilter != SummarizeStateFilters.All)
            q = q.Where(b => SummarizeStateFilters.Matches(_stateFilter, b));
        var list = q.ToList();
        BooksList.ItemsSource = list;
        StatusText.Text = list.Count == 0 ? "暂无书籍，点击「导入」开始" : $"共 {list.Count} 本";
        UpdateBatchBar();
    }

    private async void Filter_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (_suppressFilter) return;
        _categoryFilter = (CategoryBox.SelectedItem as ComboBoxItem)?.Tag as string ?? LibraryFilters.All;
        _stateFilter = (StateBox.SelectedItem as ComboBoxItem)?.Tag as string ?? SummarizeStateFilters.All;
        var newSort = (SortBox.SelectedItem as ComboBoxItem)?.Tag as string ?? LibrarySorts.Recent;
        if (newSort != _sort || sender == CategoryBox)
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
        picker.FileTypeFilter.Add("*");

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
        if (BooksList.SelectedItems.Count > 1) return;
        if (book.Status is "processing" or "error")
        {
            StatusText.Text = book.Status == "processing" ? "仍在处理中，请稍候" : "导入失败，请删除后重试";
            return;
        }
        MainWindowLocator.Current?.NavigateToReader(book.Id, book.Title);
    }

    private void BooksList_SelectionChanged(object sender, SelectionChangedEventArgs e) => UpdateBatchBar();

    private void UpdateBatchBar()
    {
        var n = BooksList.SelectedItems.Count;
        BatchBar.Visibility = n > 0 ? Visibility.Visible : Visibility.Collapsed;
        BatchCountText.Text = $"已选 {n} 本";
        if (n > 0) StatusText.Text = "";
    }

    private List<string> SelectedIds() =>
        BooksList.SelectedItems.OfType<BookSummary>().Select(b => b.Id).ToList();

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
            await App.Core.StartSummarizeBooksAsync(SelectedIds());
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

    private void ClearSelection_Click(object sender, RoutedEventArgs e) => BooksList.SelectedItems.Clear();

    private async void Favorite_Click(object sender, RoutedEventArgs e)
    {
        e.Handled = true;
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
        e.Handled = true;
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
