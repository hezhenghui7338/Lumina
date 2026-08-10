using Lumina.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace Lumina.Features.Notes;

public sealed partial class AllNotesPage : Page
{
    private CancellationTokenSource? _cts;

    public AllNotesPage()
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
        _cts?.Cancel();
        base.OnNavigatedFrom(e);
    }

    private void Back_Click(object sender, RoutedEventArgs e) =>
        MainWindowLocator.Current?.NavigateToLibrary();

    private async void Refresh_Click(object sender, RoutedEventArgs e) => await ReloadAsync();

    private async Task ReloadAsync()
    {
        _cts?.Cancel();
        _cts = new CancellationTokenSource();
        var ct = _cts.Token;
        StatusText.Text = "加载笔记…";
        try
        {
            var notes = await App.Core.ListNotesAsync(ct: ct);
            ct.ThrowIfCancellationRequested();
            NotesList.ItemsSource = notes.ToList();
            StatusText.Text = notes.Count == 0 ? "暂无笔记" : $"共 {notes.Count} 条 · 点击跳转原段";
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            StatusText.Text = ex.Message;
        }
    }

    private void Notes_ItemClick(object sender, ItemClickEventArgs e)
    {
        if (e.ClickedItem is not NoteRow note) return;
        NavigationHub.RequestOpenBook(
            note.BookId,
            note.BookTitle ?? "书籍",
            note.SegmentIndex);
    }

    private async void DeleteSelected_Click(object sender, RoutedEventArgs e)
    {
        var ids = NotesList.SelectedItems.OfType<NoteRow>().Select(n => n.Id).ToList();
        if (ids.Count == 0)
        {
            StatusText.Text = "请先选择笔记";
            return;
        }
        var dlg = new ContentDialog
        {
            Title = "删除笔记",
            Content = $"确定删除 {ids.Count} 条笔记？",
            PrimaryButtonText = "删除",
            CloseButtonText = "取消",
            XamlRoot = XamlRoot,
        };
        if (await dlg.ShowAsync() != ContentDialogResult.Primary) return;
        try
        {
            await App.Core.DeleteNotesAsync(ids);
            await ReloadAsync();
        }
        catch (Exception ex)
        {
            StatusText.Text = ex.Message;
        }
    }
}
