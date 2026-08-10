using Lumina.Design;
using Lumina.Features.Tasks;
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
        DebugToggle.Toggled += (_, _) =>
            TaskManagerBtn.Visibility = DebugToggle.IsOn ? Visibility.Visible : Visibility.Collapsed;
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
            BindSettings(_settings);
            await RefreshResourcesInternalAsync(ct);
            StatusText.Text = "已加载";
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            StatusText.Text = ex.Message;
        }
    }

    private void BindSettings(AppSettings s)
    {
        SelectCombo(TargetLanguageBox, s.TargetLanguage);
        AutoSummaryToggle.IsOn = s.AutoStartSummary;
        SelectCombo(WebProviderBox, s.WebSearchProvider);
        TavilyKeyBox.Password = s.TavilyApiKey ?? "";
        DebugToggle.IsOn = s.DebugMode;
        TaskManagerBtn.Visibility = s.DebugMode ? Visibility.Visible : Visibility.Collapsed;

        var ollama = s.Models.Resources.FirstOrDefault(r => r.Id == "ollama");
        OllamaModelBox.Text = ollama?.Model ?? "qwen3.5:4b";
        OllamaUrlBox.Text = ollama?.BaseUrl ?? "http://127.0.0.1:11434";
        var openai = s.Models.Resources.FirstOrDefault(r => r.Id == "openai");
        OpenAiKeyBox.Text = openai?.ApiKey ?? "";
        OpenAiModelBox.Text = openai?.Model ?? "gpt-4o-mini";
        var openrouter = s.Models.Resources.FirstOrDefault(r => r.Id == "openrouter");
        OpenRouterKeyBox.Text = openrouter?.ApiKey ?? "";
        OpenRouterModelBox.Text = openrouter?.Model ?? "";
        var cursor = s.Models.Resources.FirstOrDefault(r => r.Id == "cursor");
        CursorKeyBox.Text = cursor?.ApiKey ?? "";
        CursorModelBox.Text = cursor?.Model ?? "composer-2.5";
        ChatPriorityBox.Text = string.Join(",", s.Models.Chat.Priority);
        SummarizePriorityBox.Text = string.Join(",", s.Models.Summarize.Priority);

        PromptSegmentBox.Text = s.Prompts.Segment;
        PromptDocumentBox.Text = s.Prompts.Document;
        PromptChatBox.Text = s.Prompts.Chat;
        PromptNewsChatBox.Text = s.Prompts.NewsChat;
        PromptTranslateBox.Text = s.Prompts.Translate;
        PromptClassifyBox.Text = s.Prompts.Classify;
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

    private void Theme_Checked(object sender, RoutedEventArgs e)
    {
        if (ThemeDark.IsChecked == true)
            ThemeService.Apply(MainWindowLocator.Current?.Content as FrameworkElement ?? this, ElementTheme.Dark);
        else
            ThemeService.Apply(MainWindowLocator.Current?.Content as FrameworkElement ?? this, ElementTheme.Light);
    }

    private async void RefreshResources_Click(object sender, RoutedEventArgs e) =>
        await RefreshResourcesInternalAsync();

    private async Task RefreshResourcesInternalAsync(CancellationToken ct = default)
    {
        try
        {
            var status = await App.Core.FetchOllamaStatusAsync(ct: ct);
            OllamaStatusText.Text = status.Available
                ? $"Ollama 可用 · {(status.InstalledModels is { Count: > 0 } ? string.Join(", ", status.InstalledModels.Take(6)) : status.Model)}"
                : (status.Message ?? "Ollama 不可用");
            var resources = await App.Core.FetchAllResourceStatusAsync(ct);
            ResourceStatusText.Text = resources.Count == 0
                ? "无资源状态"
                : string.Join(" · ", resources.Select(r => $"{r.ResourceId}: {r.DisplayMessage}"));
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

    private void ResetPrompts_Click(object sender, RoutedEventArgs e)
    {
        if (_settings is null) return;
        var d = _settings.PromptsDefaults;
        PromptSegmentBox.Text = d.Segment;
        PromptDocumentBox.Text = d.Document;
        PromptChatBox.Text = d.Chat;
        PromptNewsChatBox.Text = d.NewsChat;
        PromptTranslateBox.Text = d.Translate;
        PromptClassifyBox.Text = d.Classify;
    }

    private void TaskManager_Click(object sender, RoutedEventArgs e) =>
        Frame.Navigate(typeof(TaskManagerPage));

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
            _settings.TargetLanguage =
                (TargetLanguageBox.SelectedItem as ComboBoxItem)?.Tag as string ?? "zh-CN";
            _settings.AutoStartSummary = AutoSummaryToggle.IsOn;
            _settings.WebSearchProvider =
                (WebProviderBox.SelectedItem as ComboBoxItem)?.Tag as string ?? "ddgs";
            _settings.TavilyApiKey = string.IsNullOrWhiteSpace(TavilyKeyBox.Password)
                ? null
                : TavilyKeyBox.Password;
            _settings.DebugMode = DebugToggle.IsOn;

            void SetResource(string id, string provider, Action<ModelResourceSettings> edit)
            {
                var r = _settings.Models.Resources.FirstOrDefault(x => x.Id == id);
                if (r is null)
                {
                    r = new ModelResourceSettings { Id = id, Provider = provider };
                    _settings.Models.Resources.Add(r);
                }
                r.Provider = provider;
                edit(r);
            }

            SetResource("ollama", "ollama", r =>
            {
                r.BaseUrl = string.IsNullOrWhiteSpace(OllamaUrlBox.Text) ? "http://127.0.0.1:11434" : OllamaUrlBox.Text.Trim();
                r.Model = string.IsNullOrWhiteSpace(OllamaModelBox.Text) ? "qwen3.5:4b" : OllamaModelBox.Text.Trim();
            });
            SetResource("openai", "openai", r =>
            {
                r.ApiKey = string.IsNullOrWhiteSpace(OpenAiKeyBox.Text) ? null : OpenAiKeyBox.Text.Trim();
                r.Model = string.IsNullOrWhiteSpace(OpenAiModelBox.Text) ? "gpt-4o-mini" : OpenAiModelBox.Text.Trim();
                if (string.IsNullOrWhiteSpace(r.BaseUrl)) r.BaseUrl = "https://api.openai.com/v1";
            });
            SetResource("openrouter", "openrouter", r =>
            {
                r.ApiKey = string.IsNullOrWhiteSpace(OpenRouterKeyBox.Text) ? null : OpenRouterKeyBox.Text.Trim();
                r.Model = OpenRouterModelBox.Text.Trim();
                if (string.IsNullOrWhiteSpace(r.BaseUrl)) r.BaseUrl = "https://openrouter.ai/api/v1";
            });
            SetResource("cursor", "cursor", r =>
            {
                r.ApiKey = string.IsNullOrWhiteSpace(CursorKeyBox.Text) ? null : CursorKeyBox.Text.Trim();
                r.Model = string.IsNullOrWhiteSpace(CursorModelBox.Text) ? "composer-2.5" : CursorModelBox.Text.Trim();
            });

            static List<string> SplitPriority(string? raw) =>
                (raw ?? "").Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).ToList();

            _settings.Models.Chat.Priority = SplitPriority(ChatPriorityBox.Text);
            _settings.Models.Summarize.Priority = SplitPriority(SummarizePriorityBox.Text);

            _settings.Prompts.Segment = PromptSegmentBox.Text ?? "";
            _settings.Prompts.Document = PromptDocumentBox.Text ?? "";
            _settings.Prompts.Chat = PromptChatBox.Text ?? "";
            _settings.Prompts.NewsChat = PromptNewsChatBox.Text ?? "";
            _settings.Prompts.Translate = PromptTranslateBox.Text ?? "";
            _settings.Prompts.Classify = PromptClassifyBox.Text ?? "";

            _settings = await App.Core.UpdateSettingsAsync(_settings);
            BindSettings(_settings);
            StatusText.Text = "已保存";
        }
        catch (Exception ex)
        {
            StatusText.Text = $"保存失败：{ex.Message}";
        }
    }
}
