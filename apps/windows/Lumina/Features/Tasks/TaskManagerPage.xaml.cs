using Lumina.Features.Settings;
using Lumina.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace Lumina.Features.Tasks;

public sealed partial class TaskManagerPage : Page
{
    private CancellationTokenSource? _cts;
    private DispatcherTimer? _poll;

    public TaskManagerPage()
    {
        InitializeComponent();
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        _ = ReloadAsync();
        _poll = new DispatcherTimer { Interval = TimeSpan.FromSeconds(2) };
        _poll.Tick += async (_, _) => await ReloadAsync();
        _poll.Start();
    }

    protected override void OnNavigatedFrom(NavigationEventArgs e)
    {
        _cts?.Cancel();
        _poll?.Stop();
        base.OnNavigatedFrom(e);
    }

    private void Back_Click(object sender, RoutedEventArgs e) =>
        Frame.Navigate(typeof(SettingsPage));

    private async void Refresh_Click(object sender, RoutedEventArgs e) => await ReloadAsync();

    private async Task ReloadAsync()
    {
        _cts?.Cancel();
        _cts = new CancellationTokenSource();
        var ct = _cts.Token;
        try
        {
            var overviewTask = App.Core.FetchOpsOverviewAsync(ct);
            var tasksTask = App.Core.FetchOpsTasksAsync(ct: ct);
            await Task.WhenAll(overviewTask, tasksTask);
            var ov = overviewTask.Result;
            var tasks = tasksTask.Result;
            OverviewText.Text =
                $"排队 {ov.TaskCounts.Queued} · 运行 {ov.TaskCounts.Running} · 完成 {ov.TaskCounts.Completed} · 失败 {ov.TaskCounts.Failed}" +
                (ov.JobQueue.UserPausedAll ? " · 用户已全部暂停" : "");
            RuntimeText.Text = string.Join(" · ",
                ov.ResourceRuntime.Select(r => $"{r.ResourceId}: {r.InUse}/{r.Limit}"));
            TasksList.ItemsSource = tasks.Tasks.ToList();
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            OverviewText.Text = ex.Message;
        }
    }

    private async void Cancel_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button { Tag: string id }) return;
        try
        {
            await App.Core.CancelOpsTaskAsync(id);
            await ReloadAsync();
        }
        catch (Exception ex)
        {
            OverviewText.Text = ex.Message;
        }
    }

    private async void StartAll_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            await App.Core.StartSummarizeAllAsync();
            await ReloadAsync();
        }
        catch (Exception ex) { OverviewText.Text = ex.Message; }
    }

    private async void StopAll_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            await App.Core.StopSummarizeAllAsync();
            await ReloadAsync();
        }
        catch (Exception ex) { OverviewText.Text = ex.Message; }
    }
}
