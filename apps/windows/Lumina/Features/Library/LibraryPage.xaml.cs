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

            var books = await App.Core.ListBooksAsync(ct: ct);
            ct.ThrowIfCancellationRequested();
            BooksList.ItemsSource = books.ToList();
            StatusText.Text = books.Count == 0 ? "暂无书籍，点击「导入」开始" : $"共 {books.Count} 本";
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

    private async void Import_Click(object sender, RoutedEventArgs e)
    {
        var window = Lumina.MainWindowLocator.Current;
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

        var file = await picker.PickSingleFileAsync();
        if (file is null) return;

        StatusText.Text = "导入中…（可继续浏览）";
        try
        {
            var path = file.Path;
            await App.Core.ImportBookAsync(path);
            StatusText.Text = "导入已提交";
            await ReloadAsync();
        }
        catch (ImportConflictException ex)
        {
            var dlg = new ContentDialog
            {
                Title = "书已存在",
                Content = $"「{ex.BookTitle}」已在书库中。是否覆盖重新导入？",
                PrimaryButtonText = "覆盖",
                CloseButtonText = "取消",
                XamlRoot = XamlRoot,
            };
            if (await dlg.ShowAsync() == ContentDialogResult.Primary)
            {
                await App.Core.ImportBookAsync(ex.Path, overwrite: true);
                await ReloadAsync();
            }
        }
        catch (Exception ex)
        {
            StatusText.Text = $"导入失败：{ex.Message}";
        }
    }

    private void BooksList_ItemClick(object sender, ItemClickEventArgs e)
    {
        if (e.ClickedItem is not BookSummary book) return;
        if (book.Status is "processing" or "error")
        {
            StatusText.Text = book.Status == "processing" ? "仍在处理中，请稍候" : "导入失败，请删除后重试";
            return;
        }
        Lumina.MainWindowLocator.Current?.NavigateToReader(book.Id, book.Title);
    }

    private async void Delete_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button { Tag: string id }) return;
        var dlg = new ContentDialog
        {
            Title = "删除书籍",
            Content = "确定从书库删除？此操作不可撤销。",
            PrimaryButtonText = "删除",
            CloseButtonText = "取消",
            XamlRoot = XamlRoot,
        };
        if (await dlg.ShowAsync() != ContentDialogResult.Primary) return;
        try
        {
            await App.Core.DeleteBookAsync(id);
            await ReloadAsync();
        }
        catch (Exception ex)
        {
            StatusText.Text = ex.Message;
        }
    }
}
