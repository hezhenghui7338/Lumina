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
    private bool _tourActive;
    private OnboardingTourStep _tourStep = OnboardingTourStep.ImportBook;
    private bool _hasOpenableBook;
    private BookSummary? _firstBook;
    private bool _suppressTipClosed;
    private int _tourGen;

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

        NavigationHub.OpenImportRequested += () => DispatcherQueue.TryEnqueue(RequestLibraryImport);
        RootGrid.KeyDown += RootGrid_KeyDown;

        ContentFrame.Navigate(typeof(LibraryPage));
        if (!ThemeService.OnboardingDone)
            _ = StartTourAsync();
    }

    private async Task StartTourAsync()
    {
        _tourActive = true;
        _tourStep = OnboardingTourStep.ImportBook;
        await RefreshTourLibraryAsync();
        await ShowTourTipAsync();
    }

    private async Task RefreshTourLibraryAsync()
    {
        try
        {
            if (!App.Sidecar.IsRunning)
            {
                _hasOpenableBook = false;
                _firstBook = null;
                return;
            }
            var books = await App.Core.ListBooksAsync();
            _firstBook = books.FirstOrDefault(b => b.CanOpenInReader);
            _hasOpenableBook = _firstBook != null;
            _tourStep = OnboardingTourPolicy.Resolve(_tourStep, _hasOpenableBook);
        }
        catch
        {
            _hasOpenableBook = false;
            _firstBook = null;
        }
    }

    private async Task ShowTourTipAsync()
    {
        if (!_tourActive) return;
        var gen = ++_tourGen;
        _suppressTipClosed = true;
        OnboardingTip.IsOpen = false;
        NavigateForTourStep();
        await Task.Delay(180);
        if (gen != _tourGen || !_tourActive) return;

        var copy = OnboardingTourPolicy.Copy(_tourStep, _hasOpenableBook);
        var idx = OnboardingTourPolicy.Index(_tourStep, _hasOpenableBook) + 1;
        var count = OnboardingTourPolicy.Count(_hasOpenableBook);
        OnboardingTip.Title = copy.Title;
        OnboardingTip.Subtitle = $"{copy.Body}\n{idx} / {count}";
        OnboardingTip.ActionButtonContent =
            OnboardingTourPolicy.PrimaryButtonTitle(_tourStep, _hasOpenableBook);
        OnboardingBackButton.Visibility = OnboardingTourPolicy.IsFirst(_tourStep, _hasOpenableBook)
            ? Visibility.Collapsed
            : Visibility.Visible;
        OnboardingTip.Target = FindTourTarget();
        OnboardingTip.IsOpen = true;
        _suppressTipClosed = false;
    }

    private void NavigateForTourStep()
    {
        switch (OnboardingTourPolicy.Surface(_tourStep))
        {
            case OnboardingTourSurface.Library:
                if (ContentFrame.Content is not LibraryPage)
                    NavigateToLibrary();
                break;
            case OnboardingTourSurface.Settings:
                if (ContentFrame.Content is not SettingsPage)
                {
                    ContentFrame.Navigate(typeof(SettingsPage));
                    SelectNav("settings");
                }
                break;
            case OnboardingTourSurface.Reader:
                if (_firstBook is { } book)
                {
                    if (ContentFrame.Content is not ReaderPage)
                        NavigateToReader(book.Id, book.Title);
                }
                else if (ContentFrame.Content is not LibraryPage)
                    NavigateToLibrary();
                break;
        }
    }

    private FrameworkElement? FindTourTarget()
    {
        var anchor = OnboardingTourPolicy.Anchor(_tourStep, _hasOpenableBook);
        return ContentFrame.Content switch
        {
            LibraryPage library => library.TourTarget(anchor),
            SettingsPage settings => settings.TourTarget(anchor),
            ReaderPage reader => reader.TourTarget(anchor),
            _ => null,
        };
    }

    private async void OnboardingNext_Click(object sender, RoutedEventArgs e)
    {
        await RefreshTourLibraryAsync();
        var next = OnboardingTourPolicy.Next(_tourStep, _hasOpenableBook);
        if (next is null)
        {
            FinishTour();
            return;
        }
        _tourStep = next.Value;
        await ShowTourTipAsync();
    }

    private async void OnboardingBack_Click(object sender, RoutedEventArgs e)
    {
        var previous = OnboardingTourPolicy.Previous(_tourStep, _hasOpenableBook);
        if (previous is null) return;
        _tourStep = previous.Value;
        await ShowTourTipAsync();
    }

    private void OnboardingSkip_Click(object sender, RoutedEventArgs e) => FinishTour();

    private void OnboardingTip_Closed(TeachingTip sender, TeachingTipClosedEventArgs args)
    {
        if (_suppressTipClosed || !_tourActive) return;
        FinishTour();
    }

    private void FinishTour()
    {
        _tourActive = false;
        _suppressTipClosed = true;
        OnboardingTip.IsOpen = false;
        if (UsageGuidePresentationPolicy.MarksOnboardingComplete(reopenOnly: false))
            ThemeService.OnboardingDone = true;
        _suppressTipClosed = false;
        if (UsageGuidePresentationPolicy.ShouldPresentGuideAfterFirstRun)
            _ = ShowUsageGuideAfterTourAsync();
    }

    private async Task ShowUsageGuideAfterTourAsync()
    {
        await Task.Delay(120);
        var root = (Content as FrameworkElement)?.XamlRoot;
        await UsageGuideDialog.ShowAsync(root);
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
            RequestLibraryImport();
            e.Handled = true;
        }
    }

    public void NavigateToReader(string bookId, string title, int? segmentIndex = null)
    {
        ContentFrame.Navigate(typeof(ReaderPage), new ReaderNavArgs(bookId, title, segmentIndex));
        SelectNav("library");
    }

    public void NavigateToLibrary(bool openImport = false)
    {
        ContentFrame.Navigate(typeof(LibraryPage), openImport ? new LibraryNavArgs(true) : null);
        SelectNav("library");
    }

    private void RequestLibraryImport()
    {
        if (ContentFrame.Content is LibraryPage page)
            _ = page.BeginImportAsync();
        else
            NavigateToLibrary(openImport: true);
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
        if (_tourActive && App.Sidecar.IsRunning)
        {
            DispatcherQueue.TryEnqueue(async () =>
            {
                var before = _tourStep;
                await RefreshTourLibraryAsync();
                if (_tourActive && before != _tourStep)
                    await ShowTourTipAsync();
            });
        }
    }

    private void UpdateEngineStatus()
    {
        if (App.Sidecar.IsRunning)
            EngineStatusText.Text = "引擎已就绪";
        else if (App.Sidecar.IsBootstrapping)
            EngineStatusText.Text = "引擎启动中…";
        else if (!string.IsNullOrEmpty(App.Sidecar.LaunchError))
            EngineStatusText.Text = App.Sidecar.LaunchError;
        else if (App.Sidecar.UserStopped)
            EngineStatusText.Text = "引擎已停止";
        else
            EngineStatusText.Text = "引擎未运行";
    }

    private async void RetryEngine_Click(object sender, RoutedEventArgs e)
    {
        EngineStatusText.Text = "引擎启动中…";
        App.Sidecar.ClearUserStopped();
        await App.Sidecar.EnsureRunningAsync();
        UpdateEngineStatus();
    }
}
