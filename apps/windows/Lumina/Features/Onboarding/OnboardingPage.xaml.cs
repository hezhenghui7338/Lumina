using Lumina.Design;
using Lumina.Features.Library;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;
using Windows.System;

namespace Lumina.Features.Onboarding;

public sealed partial class OnboardingPage : Page
{
    public OnboardingPage()
    {
        InitializeComponent();
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        _ = RefreshAsync();
    }

    private async Task RefreshAsync()
    {
        if (!App.Sidecar.IsRunning)
            await App.Sidecar.EnsureRunningAsync();

        EngineText.Text = App.Sidecar.IsRunning
            ? "引擎已就绪。"
            : (App.Sidecar.LaunchError ?? "引擎启动中，请稍候…");

        await CheckOllamaInternalAsync();
    }

    private async void OpenOllama_Click(object sender, RoutedEventArgs e)
    {
        await Launcher.LaunchUriAsync(new Uri("https://ollama.com/download"));
    }

    private async void CheckOllama_Click(object sender, RoutedEventArgs e)
    {
        await CheckOllamaInternalAsync();
    }

    private async Task CheckOllamaInternalAsync()
    {
        if (!App.Sidecar.IsRunning)
        {
            OllamaText.Text = "请先等待引擎就绪。";
            return;
        }
        try
        {
            var status = await App.Core.FetchOllamaStatusAsync();
            if (status.Available)
            {
                var models = status.InstalledModels is { Count: > 0 }
                    ? string.Join(", ", status.InstalledModels.Take(5))
                    : status.Model;
                OllamaText.Text = $"Ollama 可用。模型：{models}";
            }
            else
            {
                OllamaText.Text = status.Message ?? "未检测到 Ollama，请安装并启动。";
            }
        }
        catch (Exception ex)
        {
            OllamaText.Text = ex.Message;
        }
    }

    private void Finish_Click(object sender, RoutedEventArgs e)
    {
        ThemeService.OnboardingDone = true;
        Frame.Navigate(typeof(LibraryPage));
    }
}
