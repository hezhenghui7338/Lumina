using Lumina.Design;
using Lumina.Features.Library;
using Lumina.Features.News;
using Lumina.Features.Notes;
using Lumina.Features.Onboarding;
using Lumina.Features.Reader;
using Lumina.Features.Search;
using Lumina.Features.Settings;
using Lumina.Features.Tasks;
using Lumina.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Windows.System;

namespace Lumina;

internal static class MainWindowLocator
{
    public static MainWindow? Current { get; set; }
}

public sealed partial class MainWindow : Window
{
    public MainWindow()
    {
        InitializeComponent();
        MainWindowLocator.Current = this;
        ThemeService.Load();
        if (Content is FrameworkElement root)
            root.RequestedTheme = ThemeService.Current;

        App.Sidecar.StateChanged += OnSidecarStateChanged;
        UpdateEngineStatus();

        NavigationHub.OpenBookRequested += OnOpenBookRequested;
        NavigationHub.OpenAllNotesRequested += () =>
        {
            DispatcherQueue.TryEnqueue(() =>
            {
                ContentFrame.Navigate(typeof(AllNotesPage));
                SelectNav("library");
            });
        };
        NavigationHub.OpenSearchRequested += () => DispatcherQueue.TryEnqueue(ShowSearch);
        NavigationHub.OpenTaskManagerRequested += () =>
        {
            DispatcherQueue.TryEnqueue(() =>
            {
                ContentFrame.Navigate(typeof(TaskManagerPage));
                SelectNav("settings");
            });
        };

        RootGrid.KeyDown += RootGrid_KeyDown;

        if (!ThemeService.OnboardingDone)
            ContentFrame.Navigate(typeof(OnboardingPage));
        else
            ContentFrame.Navigate(typeof(LibraryPage));
    }

    private void RootGrid_KeyDown(object sender, KeyRoutedEventArgs e)
    {
        var ctrl = Microsoft.UI.Input.InputKeyboardSource.GetKeyStateForCurrentThread(VirtualKey.Control)
            .HasFlag(Windows.UI.Core.CoreVirtualKeyStates.Down);
        if (!ctrl) return;
        if (e.Key == VirtualKey.K)
        {
            ShowSearch();
            e.Handled = true;
        }
        else if (e.Key == VirtualKey.O)
        {
            // Import is owned by library page; switch there and raise hub if needed.
            NavigateToLibrary();
            e.Handled = true;
        }
    }

    public void NavigateToReader(string bookId, string title, int? segmentIndex = null)
    {
        ContentFrame.Navigate(typeof(ReaderPage), new ReaderNavArgs(bookId, title, segmentIndex));
        SelectNav("library");
    }

    public void NavigateToLibrary()
    {
        ContentFrame.Navigate(typeof(LibraryPage));
        SelectNav("library");
    }

    private void OnOpenBookRequested(string bookId, string title, int? segmentIndex)
    {
        DispatcherQueue.TryEnqueue(() => NavigateToReader(bookId, title, segmentIndex));
    }

    private void NavView_SelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        if (args.SelectedItem is NavigationViewItem item && item.Tag is string tag)
        {
            switch (tag)
            {
                case "library":
                    ContentFrame.Navigate(typeof(LibraryPage));
                    break;
                case "news":
                    ContentFrame.Navigate(typeof(NewsPage));
                    break;
                case "settings":
                    ContentFrame.Navigate(typeof(SettingsPage));
                    break;
            }
        }
    }

    private void SelectNav(string tag)
    {
        foreach (var obj in NavView.MenuItems)
        {
            if (obj is NavigationViewItem item && item.Tag as string == tag)
            {
                NavView.SelectedItem = item;
                break;
            }
        }
    }

    private void Search_Click(object sender, RoutedEventArgs e) => ShowSearch();

    private void ShowSearch()
    {
        ContentFrame.Navigate(typeof(SearchPage));
    }

    private void OnSidecarStateChanged()
    {
        DispatcherQueue.TryEnqueue(UpdateEngineStatus);
    }

    private void UpdateEngineStatus()
    {
        if (App.Sidecar.IsRunning)
            EngineStatusText.Text = "引擎已就绪";
        else if (App.Sidecar.IsBootstrapping)
            EngineStatusText.Text = "引擎启动中…";
        else if (!string.IsNullOrEmpty(App.Sidecar.LaunchError))
            EngineStatusText.Text = App.Sidecar.LaunchError;
        else
            EngineStatusText.Text = "引擎未运行";
    }

    private async void RetryEngine_Click(object sender, RoutedEventArgs e)
    {
        EngineStatusText.Text = "引擎启动中…";
        await App.Sidecar.EnsureRunningAsync();
        UpdateEngineStatus();
    }
}
