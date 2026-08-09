using Lumina.Design;
using Lumina.Features.Library;
using Lumina.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;
using Windows.System;

namespace Lumina.Features.Settings;

public sealed partial class SettingsPage : Page
{
    private AppSettings? _settings;
    private CancellationTokenSource? _cts;

    public SettingsPage()
    {
        InitializeComponent();
        ThemeLight.IsChecked = ThemeService.Current != ElementTheme.Dark;
        ThemeDark.IsChecked = ThemeService.Current == ElementTheme.Dark;
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        _ = LoadAsync();
    }

    protected override void OnNavigatedFrom(NavigationEventArgs e)
    {
        _cts?.Cancel();
        base.OnNavigatedFrom(e);
    }

    private async Task LoadAsync()
    {
        _cts?.Cancel();
        _cts = new CancellationTokenSource();
        var ct = _cts.Token;
        StatusText.Text = "加载设置…";
        try
        {
            if (!App.Sidecar.IsRunning)
                await App.Sidecar.EnsureRunningAsync(ct);
            _settings = await App.Core.FetchSettingsAsync(ct);
            TargetLanguageBox.Text = _settings.TargetLanguage;
            AutoSummaryToggle.IsOn = _settings.AutoStartSummary;
            SelectProvider(_settings.WebSearchProvider);
            TavilyKeyBox.Password = _settings.TavilyApiKey ?? "";

            var ollama = _settings.Models.Resources.FirstOrDefault(r => r.Id == "ollama");
            OllamaModelBox.Text = ollama?.Model ?? "qwen3.5:4b";
            var openai = _settings.Models.Resources.FirstOrDefault(r => r.Id == "openai");
            OpenAiKeyBox.Text = openai?.ApiKey ?? "";
            var openrouter = _settings.Models.Resources.FirstOrDefault(r => r.Id == "openrouter");
            OpenRouterKeyBox.Text = openrouter?.ApiKey ?? "";

            await RefreshOllamaInternalAsync(ct);
            StatusText.Text = "已加载";
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            StatusText.Text = ex.Message;
        }
    }

    private void SelectProvider(string provider)
    {
        foreach (var item in WebProviderBox.Items.OfType<ComboBoxItem>())
        {
            if (item.Tag as string == provider)
            {
                WebProviderBox.SelectedItem = item;
                return;
            }
        }
    }

    private void Theme_Checked(object sender, RoutedEventArgs e)
    {
        if (ThemeDark.IsChecked == true)
            ThemeService.Apply(Lumina.MainWindowLocator.Current?.Content as FrameworkElement ?? this, ElementTheme.Dark);
        else
            ThemeService.Apply(Lumina.MainWindowLocator.Current?.Content as FrameworkElement ?? this, ElementTheme.Light);
    }

    private async void RefreshOllama_Click(object sender, RoutedEventArgs e)
    {
        await RefreshOllamaInternalAsync();
    }

    private async Task RefreshOllamaInternalAsync(CancellationToken ct = default)
    {
        try
        {
            var status = await App.Core.FetchOllamaStatusAsync(ct);
            OllamaStatusText.Text = status.Available
                ? $"可用 · 模型：{(status.InstalledModels is { Count: > 0 } ? string.Join(", ", status.InstalledModels.Take(6)) : status.Model)}"
                : (status.Message ?? "不可用");
        }
        catch (Exception ex)
        {
            OllamaStatusText.Text = ex.Message;
        }
    }

    private async void OpenOllama_Click(object sender, RoutedEventArgs e)
    {
        await Launcher.LaunchUriAsync(new Uri("https://ollama.com/download"));
    }

    private async void Save_Click(object sender, RoutedEventArgs e)
    {
        if (_settings is null)
        {
            StatusText.Text = "设置尚未加载";
            return;
        }
        StatusText.Text = "保存中…";
        try
        {
            _settings.TargetLanguage = TargetLanguageBox.Text.Trim();
            _settings.AutoStartSummary = AutoSummaryToggle.IsOn;
            _settings.WebSearchProvider =
                (WebProviderBox.SelectedItem as ComboBoxItem)?.Tag as string ?? "ddgs";
            _settings.TavilyApiKey = string.IsNullOrWhiteSpace(TavilyKeyBox.Password)
                ? null
                : TavilyKeyBox.Password;

            void SetResource(string id, Action<ModelResourceSettings> edit)
            {
                var r = _settings.Models.Resources.FirstOrDefault(x => x.Id == id);
                if (r is null)
                {
                    r = new ModelResourceSettings { Id = id, Provider = id };
                    _settings.Models.Resources.Add(r);
                }
                edit(r);
            }

            SetResource("ollama", r =>
            {
                r.Provider = "ollama";
                r.BaseUrl = string.IsNullOrWhiteSpace(r.BaseUrl) ? "http://127.0.0.1:11434" : r.BaseUrl;
                r.Model = string.IsNullOrWhiteSpace(OllamaModelBox.Text) ? "qwen3.5:4b" : OllamaModelBox.Text.Trim();
            });
            SetResource("openai", r =>
            {
                r.Provider = "openai";
                r.ApiKey = string.IsNullOrWhiteSpace(OpenAiKeyBox.Text) ? null : OpenAiKeyBox.Text.Trim();
            });
            SetResource("openrouter", r =>
            {
                r.Provider = "openrouter";
                r.ApiKey = string.IsNullOrWhiteSpace(OpenRouterKeyBox.Text) ? null : OpenRouterKeyBox.Text.Trim();
            });

            _settings = await App.Core.UpdateSettingsAsync(_settings);
            StatusText.Text = "已保存";
        }
        catch (Exception ex)
        {
            StatusText.Text = $"保存失败：{ex.Message}";
        }
    }
}
