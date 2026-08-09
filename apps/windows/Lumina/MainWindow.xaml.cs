using Lumina.Design;
using Lumina.Features.Library;
using Lumina.Features.Onboarding;
using Lumina.Features.Reader;
using Lumina.Features.Settings;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

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

        if (!ThemeService.OnboardingDone)
            ContentFrame.Navigate(typeof(OnboardingPage));
        else
            ContentFrame.Navigate(typeof(LibraryPage));
    }

    public void NavigateToReader(string bookId, string title)
    {
        ContentFrame.Navigate(typeof(ReaderPage), new ReaderNavArgs(bookId, title));
    }

    public void NavigateToLibrary()
    {
        ContentFrame.Navigate(typeof(LibraryPage));
        SelectNav("library");
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
