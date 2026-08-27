using System.Globalization;
using Lumina.Design;
using Lumina.Features.Onboarding;
using Lumina.Features.Reader.Listen;
using Lumina.Features.Shared;
using Lumina.Features.Tasks;
using Lumina.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;
using Windows.Media.SpeechSynthesis;
using Windows.System;

namespace Lumina.Features.Settings;

public sealed partial class SettingsPage : Page
{
    private AppSettings? _settings;
    private CancellationTokenSource? _cts;
    private readonly Dictionary<string, int> _probedChunkTargets = [];
    private readonly HashSet<string> _probing = [];
    private readonly Dictionary<string, TextBlock> _customProbeTexts = [];
    private readonly Dictionary<string, Button> _customProbeButtons = [];
    private bool _listeningActivation;
    private bool _chunkPresetsWired;

    public SettingsPage()
    {
        InitializeComponent();
        ThemeLight.IsChecked = ThemeService.Current != ElementTheme.Dark;
        ThemeDark.IsChecked = ThemeService.Current == ElementTheme.Dark;
        DebugToggle.Toggled += (_, _) =>
            TaskManagerBtn.Visibility = DebugToggle.IsOn ? Visibility.Visible : Visibility.Collapsed;
        WireChunkPresets();
    }

    internal FrameworkElement? TourTarget(OnboardingTourAnchor anchor) =>
        anchor == OnboardingTourAnchor.ApiResources ? ApiResourcesHeader : null;

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        App.Sidecar.StateChanged += OnSidecarStateChanged;
        UpdateEngineRunStatus();
        _ = LoadAsync();
        if (MainWindowLocator.Current is { } win && !_listeningActivation)
        {
            win.Activated += OnMainWindowActivated;
            _listeningActivation = true;
        }
    }

    protected override void OnNavigatedFrom(NavigationEventArgs e)
    {
        if (_listeningActivation && MainWindowLocator.Current is { } win)
        {
            win.Activated -= OnMainWindowActivated;
            _listeningActivation = false;
        }
        _cts?.Cancel();
        App.Sidecar.StateChanged -= OnSidecarStateChanged;
        base.OnNavigatedFrom(e);
    }

    private void OnMainWindowActivated(object sender, WindowActivatedEventArgs e)
    {
        if (e.WindowActivationState == WindowActivationState.Deactivated) return;
        RefreshListenVoices();
    }

    private async Task LoadAsync()
    {
        _cts?.Cancel();
        _cts = new CancellationTokenSource();
        var ct = _cts.Token;
        StatusText.Text = "加载设置…";
        try
        {
            if (!App.Sidecar.IsRunning && !App.Sidecar.UserStopped)
                await App.Sidecar.EnsureRunningAsync(ct);
            if (!App.Sidecar.IsRunning)
            {
                UpdateEngineRunStatus();
                if (App.Sidecar.UserStopped)
                    StatusText.Text = "引擎已停止";
                else
                    StatusText.Text = App.Sidecar.LaunchError ?? "引擎未就绪";
                return;
            }
            _settings = await App.Core.FetchSettingsAsync(ct);
            BindSettings(_settings);
            await RefreshOcrStatusAsync(ct);
            await RefreshResourcesInternalAsync(ct);
            StatusText.Text = "已加载";
            UpdateEngineRunStatus();
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
        SelectCombo(DefaultSegmentTierBox, string.IsNullOrWhiteSpace(s.DefaultSegmentTier) ? "normal" : s.DefaultSegmentTier);
        WebSearchToggle.IsOn = s.WebSearchEnabled;
        SelectCombo(WebProviderBox, s.WebSearchProvider);
        TavilyKeyBox.Password = s.TavilyApiKey ?? "";
        OcrBaseUrlBox.Text = s.OcrCloudBaseUrl;
        OcrModelBox.Text = s.OcrCloudModel;
        OcrKeyBox.Password = s.OcrCloudApiKey ?? "";
        DebugToggle.IsOn = s.DebugMode;
        TaskManagerBtn.Visibility = s.DebugMode ? Visibility.Visible : Visibility.Collapsed;

        var ollama = s.Models.Resources.FirstOrDefault(r => r.Id == "ollama");
        OllamaModelBox.Text = ollama?.Model ?? "qwen3.5:4b";
        OllamaAdvancedModelBox.Text = ollama?.AdvancedModel ?? "";
        OllamaUrlBox.Text = ollama?.BaseUrl ?? "http://127.0.0.1:11434";
        var openai = s.Models.Resources.FirstOrDefault(r => r.Id == "openai");
        OpenAiKeyBox.Text = openai?.ApiKey ?? "";
        OpenAiModelBox.Text = openai?.Model ?? "gpt-4o-mini";
        OpenAiAdvancedModelBox.Text = openai?.AdvancedModel ?? "";
        var openrouter = s.Models.Resources.FirstOrDefault(r => r.Id == "openrouter");
        OpenRouterKeyBox.Text = openrouter?.ApiKey ?? "";
        OpenRouterModelBox.Text = openrouter?.Model ?? "";
        OpenRouterAdvancedModelBox.Text = openrouter?.AdvancedModel ?? "";
        var cursor = s.Models.Resources.FirstOrDefault(r => r.Id == "cursor");
        CursorKeyBox.Text = cursor?.ApiKey ?? "";
        CursorModelBox.Text = cursor?.Model ?? "composer-2.5";
        CursorAdvancedModelBox.Text = cursor?.AdvancedModel ?? "";
        BindChunkTarget(OllamaChunkTargetBox, "ollama", ollama?.ChunkTargetChars);
        BindChunkTarget(OpenAiChunkTargetBox, "openai", openai?.ChunkTargetChars);
        BindChunkTarget(OpenRouterChunkTargetBox, "openrouter", openrouter?.ChunkTargetChars);
        BindChunkTarget(CursorChunkTargetBox, "cursor", cursor?.ChunkTargetChars);
        ChatPriorityBox.Text = string.Join(",", s.Models.Chat.Priority);
        SummarizePriorityBox.Text = string.Join(",", s.Models.Summarize.Priority);
        BindListenSettings(s);

        PromptSegmentBox.Text = s.Prompts.Segment;
        PromptSegmentOllamaBox.Text = s.Prompts.SegmentOllama ?? "";
        PromptSegmentCloudBox.Text = s.Prompts.SegmentCloud ?? "";
        PromptDocumentBox.Text = s.Prompts.Document;
        PromptChatBox.Text = s.Prompts.Chat;
        PromptNewsChatBox.Text = s.Prompts.NewsChat;
        PromptTranslateBox.Text = s.Prompts.Translate;
        PromptClassifyBox.Text = s.Prompts.Classify;
        BindCustomResources(s);
    }

    private void BindCustomResources(AppSettings s)
    {
        CustomResourcesHost.Children.Clear();
        _customProbeTexts.Clear();
        _customProbeButtons.Clear();
        var custom = s.Models.Resources
            .Where(r => CustomResourceDraft.CanDelete(r.Id))
            .ToList();
        CustomResourcesEmpty.Visibility = custom.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        foreach (var resource in custom)
        {
            var id = resource.Id;
            var row = new StackPanel { Spacing = 4 };
            var head = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
            var label = resource.ChunkTargetChars is int chars and > 0
                ? $"{resource.Id} · {resource.Model} · 分段 {chars} 字"
                : $"{resource.Id} · {resource.Model}";
            head.Children.Add(new TextBlock
            {
                Text = label,
                VerticalAlignment = VerticalAlignment.Center,
                TextWrapping = TextWrapping.WrapWholeWords,
            });
            var probeBtn = new Button
            {
                Content = _probing.Contains(id) ? "取消测试" : "测上下文",
                Tag = id,
            };
            probeBtn.Click += ProbeContext_Click;
            var deleteBtn = new Button { Content = "删除", Tag = id };
            deleteBtn.Click += DeleteCustomResource_Click;
            head.Children.Add(probeBtn);
            head.Children.Add(deleteBtn);
            var probeText = new TextBlock
            {
                TextWrapping = TextWrapping.WrapWholeWords,
                Opacity = 0.75,
            };
            _customProbeButtons[id] = probeBtn;
            _customProbeTexts[id] = probeText;
            row.Children.Add(head);
            row.Children.Add(probeText);
            CustomResourcesHost.Children.Add(row);
        }
    }

    private async void AddCustomResource_Click(object sender, RoutedEventArgs e)
    {
        if (_settings is null)
        {
            StatusText.Text = "设置尚未加载";
            return;
        }
        var idBox = new TextBox { Header = "资源 id", PlaceholderText = "my-llm" };
        var urlBox = new TextBox { Header = "Base URL", PlaceholderText = "https://api.example.com/v1" };
        var modelBox = new TextBox { Header = "模型", PlaceholderText = "gpt-4o-mini" };
        var advancedBox = new TextBox { Header = "高级模型（可选）" };
        var keyBox = new PasswordBox { Header = "API Key（可选）" };
        var hint = new TextBlock
        {
            Text = "添加后立即保存。测上下文在列表里点，因为引擎需要先登记该资源。",
            Opacity = 0.75,
            TextWrapping = TextWrapping.WrapWholeWords,
        };
        var error = new TextBlock
        {
            Foreground = new Microsoft.UI.Xaml.Media.SolidColorBrush(Windows.UI.Color.FromArgb(255, 196, 80, 40)),
            TextWrapping = TextWrapping.Wrap,
        };
        var panel = new StackPanel { Spacing = 8, Width = 360 };
        panel.Children.Add(idBox);
        panel.Children.Add(urlBox);
        panel.Children.Add(modelBox);
        panel.Children.Add(advancedBox);
        panel.Children.Add(keyBox);
        panel.Children.Add(hint);
        panel.Children.Add(error);
        var dlg = new ContentDialog
        {
            Title = "添加自定义资源",
            Content = panel,
            PrimaryButtonText = "添加并保存",
            CloseButtonText = "取消",
            XamlRoot = XamlRoot,
            DefaultButton = ContentDialogButton.Primary,
        };
        dlg.PrimaryButtonClick += (_, args) =>
        {
            var err = CustomResourceDraft.Validate(
                idBox.Text, urlBox.Text, modelBox.Text,
                _settings.Models.Resources.Select(r => r.Id));
            if (err is null) return;
            error.Text = err;
            args.Cancel = true;
        };
        if (await dlg.ShowAsync() != ContentDialogResult.Primary) return;
        _settings.Models.Resources.Add(CustomResourceDraft.Build(
            idBox.Text, urlBox.Text, modelBox.Text, advancedBox.Text, keyBox.Password));
        await FlushSettingsAsync("已添加自定义资源", captureForm: true);
    }

    private async void DeleteCustomResource_Click(object sender, RoutedEventArgs e)
    {
        if (_settings is null) return;
        if (sender is not Button { Tag: string id } || !CustomResourceDraft.CanDelete(id)) return;
        var dlg = new ContentDialog
        {
            Title = "删除自定义资源",
            Content = $"确定删除「{id}」？深聊/摘要优先级里的同一 id 也会去掉。",
            PrimaryButtonText = "删除",
            CloseButtonText = "取消",
            DefaultButton = ContentDialogButton.Close,
            XamlRoot = XamlRoot,
        };
        if (await dlg.ShowAsync() != ContentDialogResult.Primary) return;
        CaptureFormIntoSettings();
        CustomResourceDraft.Detach(
            _settings.Models.Resources,
            _settings.Models.Chat.Priority,
            _settings.Models.Summarize.Priority,
            id);
        _probedChunkTargets.Remove(id);
        await FlushSettingsAsync($"已删除 {id}", captureForm: false);
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

    private async Task RefreshOcrStatusAsync(CancellationToken ct = default)
    {
        try
        {
            var status = await App.Core.FetchOcrStatusAsync(ct);
            OcrStatusText.Text = $"{(status.Provider == "cloud" ? "云端" : "本地")} · {status.DisplayMessage}";
        }
        catch (Exception ex)
        {
            OcrStatusText.Text = ex.Message;
        }
    }

    private void ApplyOcrSettings()
    {
        if (_settings is null) return;
        _settings.OcrCloudBaseUrl = OcrBaseUrlBox.Text?.Trim() ?? "";
        _settings.OcrCloudModel = OcrModelBox.Text?.Trim() ?? "";
        _settings.OcrCloudApiKey = string.IsNullOrWhiteSpace(OcrKeyBox.Password)
            ? null
            : OcrKeyBox.Password.Trim();
    }

    private async void TestOcr_Click(object sender, RoutedEventArgs e)
    {
        if (_settings is null) return;
        OcrStatusText.Text = "保存并测试中…";
        try
        {
            ApplyOcrSettings();
            _settings = await App.Core.UpdateSettingsAsync(_settings, _cts?.Token ?? default);
            BindSettings(_settings);
            await RefreshOcrStatusAsync(_cts?.Token ?? default);
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            OcrStatusText.Text = $"测试失败：{ex.Message}";
        }
    }

    private void ResetPrompts_Click(object sender, RoutedEventArgs e)
    {
        if (_settings is null) return;
        var d = _settings.PromptsDefaults;
        PromptSegmentBox.Text = d.Segment;
        PromptSegmentOllamaBox.Text = d.SegmentOllama ?? "";
        PromptSegmentCloudBox.Text = d.SegmentCloud ?? "";
        PromptDocumentBox.Text = d.Document;
        PromptChatBox.Text = d.Chat;
        PromptNewsChatBox.Text = d.NewsChat;
        PromptTranslateBox.Text = d.Translate;
        PromptClassifyBox.Text = d.Classify;
    }

    private void TaskManager_Click(object sender, RoutedEventArgs e) =>
        Frame.Navigate(typeof(TaskManagerPage));

    private async void UsageGuide_Click(object sender, RoutedEventArgs e)
    {
        await UsageGuideDialog.ShowAsync(XamlRoot);
    }

    private async void Save_Click(object sender, RoutedEventArgs e) =>
        await FlushSettingsAsync("已保存", captureForm: true);

    private void CaptureFormIntoSettings()
    {
        if (_settings is null) return;
        _settings.TargetLanguage =
            (TargetLanguageBox.SelectedItem as ComboBoxItem)?.Tag as string ?? "zh-CN";
        _settings.AutoStartSummary = AutoSummaryToggle.IsOn;
        _settings.DefaultSegmentTier =
            (DefaultSegmentTierBox.SelectedItem as ComboBoxItem)?.Tag as string ?? "normal";
        _settings.WebSearchEnabled = WebSearchToggle.IsOn;
        _settings.WebSearchProvider =
            (WebProviderBox.SelectedItem as ComboBoxItem)?.Tag as string ?? "ddgs";
        _settings.TavilyApiKey = string.IsNullOrWhiteSpace(TavilyKeyBox.Password)
            ? null
            : TavilyKeyBox.Password;
        ApplyOcrSettings();
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
            r.AdvancedModel = string.IsNullOrWhiteSpace(OllamaAdvancedModelBox.Text) ? null : OllamaAdvancedModelBox.Text.Trim();
        });
        SetResource("openai", "openai", r =>
        {
            r.ApiKey = string.IsNullOrWhiteSpace(OpenAiKeyBox.Text) ? null : OpenAiKeyBox.Text.Trim();
            r.Model = string.IsNullOrWhiteSpace(OpenAiModelBox.Text) ? "gpt-4o-mini" : OpenAiModelBox.Text.Trim();
            r.AdvancedModel = string.IsNullOrWhiteSpace(OpenAiAdvancedModelBox.Text) ? null : OpenAiAdvancedModelBox.Text.Trim();
            if (string.IsNullOrWhiteSpace(r.BaseUrl)) r.BaseUrl = "https://api.openai.com/v1";
        });
        SetResource("openrouter", "openrouter", r =>
        {
            r.ApiKey = string.IsNullOrWhiteSpace(OpenRouterKeyBox.Text) ? null : OpenRouterKeyBox.Text.Trim();
            r.Model = OpenRouterModelBox.Text.Trim();
            r.AdvancedModel = string.IsNullOrWhiteSpace(OpenRouterAdvancedModelBox.Text) ? null : OpenRouterAdvancedModelBox.Text.Trim();
            if (string.IsNullOrWhiteSpace(r.BaseUrl)) r.BaseUrl = "https://openrouter.ai/api/v1";
        });
        SetResource("cursor", "cursor", r =>
        {
            r.ApiKey = string.IsNullOrWhiteSpace(CursorKeyBox.Text) ? null : CursorKeyBox.Text.Trim();
            r.Model = string.IsNullOrWhiteSpace(CursorModelBox.Text) ? "composer-2.5" : CursorModelBox.Text.Trim();
            r.AdvancedModel = string.IsNullOrWhiteSpace(CursorAdvancedModelBox.Text) ? null : CursorAdvancedModelBox.Text.Trim();
        });

        foreach (var (id, chars) in _probedChunkTargets)
        {
            var resource = _settings.Models.Resources.FirstOrDefault(x => x.Id == id);
            if (resource is not null)
                resource.ChunkTargetChars = chars;
        }
        WriteChunkTargetsFromUi();

        static List<string> SplitPriority(string? raw) =>
            (raw ?? "").Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).ToList();

        _settings.Models.Chat.Priority = SplitPriority(ChatPriorityBox.Text);
        _settings.Models.Summarize.Priority = SplitPriority(SummarizePriorityBox.Text);
        ApplyListenSettings();

        _settings.Prompts.Segment = PromptSegmentBox.Text ?? "";
        _settings.Prompts.SegmentOllama = string.IsNullOrWhiteSpace(PromptSegmentOllamaBox.Text) ? null : PromptSegmentOllamaBox.Text;
        _settings.Prompts.SegmentCloud = string.IsNullOrWhiteSpace(PromptSegmentCloudBox.Text) ? null : PromptSegmentCloudBox.Text;
        _settings.Prompts.Document = PromptDocumentBox.Text ?? "";
        _settings.Prompts.Chat = PromptChatBox.Text ?? "";
        _settings.Prompts.NewsChat = PromptNewsChatBox.Text ?? "";
        _settings.Prompts.Translate = PromptTranslateBox.Text ?? "";
        _settings.Prompts.Classify = PromptClassifyBox.Text ?? "";
    }

    private async Task FlushSettingsAsync(string okMessage, bool captureForm)
    {
        if (_settings is null)
        {
            StatusText.Text = "设置尚未加载";
            return;
        }
        StatusText.Text = "保存中…";
        try
        {
            if (captureForm)
                CaptureFormIntoSettings();
            _settings = await App.Core.UpdateSettingsAsync(_settings);
            BindSettings(_settings);
            await RefreshOcrStatusAsync();
            StatusText.Text = okMessage;
        }
        catch (Exception ex)
        {
            StatusText.Text = $"保存失败：{ex.Message}";
        }
    }

    private async void ProbeContext_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button button || button.Tag is not string resourceId)
            return;
        var ct = _cts?.Token ?? default;
        if (_probing.Contains(resourceId))
        {
            try
            {
                await App.Core.CancelContextProbeAsync(resourceId, ct);
            }
            catch (OperationCanceledException) { }
            catch (Exception ex)
            {
                ProbeText(resourceId).Text = ex.Message;
            }
            return;
        }
        await RunContextProbeAsync(resourceId, ct);
    }

    private async Task RunContextProbeAsync(string resourceId, CancellationToken ct)
    {
        _probing.Add(resourceId);
        SetProbeButtonLabel(resourceId, "取消测试");
        ProbeText(resourceId).Text = "正在测试后面的段是否仍被理解…";
        try
        {
            var (model, baseUrl, apiKey) = ProbeOverrides(resourceId);
            await App.Core.StartContextProbeAsync(resourceId, model, baseUrl, apiKey, ct);
            while (!ct.IsCancellationRequested)
            {
                var status = await App.Core.FetchContextProbeAsync(resourceId, ct);
                ProbeText(resourceId).Text = status.DisplayMessage;
                if (!status.IsRunning)
                {
                    if (status.Status == "done" && status.RecommendedChars is int recommended and > 0)
                    {
                        _probedChunkTargets[resourceId] = recommended;
                        if (_settings?.Models.Resources.FirstOrDefault(r => r.Id == resourceId) is { } resource)
                            resource.ChunkTargetChars = recommended;
                        SetChunkBox(resourceId, recommended);
                    }
                    break;
                }
                await Task.Delay(500, ct);
            }
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            ProbeText(resourceId).Text = $"测试失败：{ex.Message}";
        }
        finally
        {
            _probing.Remove(resourceId);
            SetProbeButtonLabel(resourceId, "测上下文");
        }
    }

    private void SetProbeButtonLabel(string resourceId, string label)
    {
        if (BuiltinProbeButton(resourceId) is { } builtin)
            builtin.Content = label;
        else if (_customProbeButtons.TryGetValue(resourceId, out var custom))
            custom.Content = label;
    }

    private Button? BuiltinProbeButton(string resourceId) => resourceId switch
    {
        "openai" => OpenAiProbeBtn,
        "openrouter" => OpenRouterProbeBtn,
        "cursor" => CursorProbeBtn,
        "ollama" => OllamaProbeBtn,
        _ => null,
    };

    private TextBlock ProbeText(string resourceId) => resourceId switch
    {
        "openai" => OpenAiProbeText,
        "openrouter" => OpenRouterProbeText,
        "cursor" => CursorProbeText,
        "ollama" => OllamaProbeText,
        _ when _customProbeTexts.TryGetValue(resourceId, out var custom) => custom,
        _ => OllamaProbeText,
    };

    private (string? model, string? baseUrl, string? apiKey) ProbeOverrides(string resourceId) => resourceId switch
    {
        "openai" => (
            OpenAiModelBox.Text?.Trim(),
            null,
            string.IsNullOrWhiteSpace(OpenAiKeyBox.Text) ? null : OpenAiKeyBox.Text.Trim()),
        "openrouter" => (
            OpenRouterModelBox.Text?.Trim(),
            null,
            string.IsNullOrWhiteSpace(OpenRouterKeyBox.Text) ? null : OpenRouterKeyBox.Text.Trim()),
        "cursor" => (
            CursorModelBox.Text?.Trim(),
            null,
            string.IsNullOrWhiteSpace(CursorKeyBox.Text) ? null : CursorKeyBox.Text.Trim()),
        "ollama" => (
            OllamaModelBox.Text?.Trim(),
            string.IsNullOrWhiteSpace(OllamaUrlBox.Text) ? null : OllamaUrlBox.Text.Trim(),
            null),
        _ => CustomProbeOverrides(resourceId),
    };

    private (string? model, string? baseUrl, string? apiKey) CustomProbeOverrides(string resourceId)
    {
        var resource = _settings?.Models.Resources.FirstOrDefault(r =>
            string.Equals(r.Id, resourceId, StringComparison.OrdinalIgnoreCase));
        if (resource is null) return (null, null, null);
        return (
            string.IsNullOrWhiteSpace(resource.Model) ? null : resource.Model.Trim(),
            string.IsNullOrWhiteSpace(resource.BaseUrl) ? null : resource.BaseUrl.Trim(),
            string.IsNullOrWhiteSpace(resource.ApiKey) ? null : resource.ApiKey.Trim());
    }

    private void WireChunkPresets()
    {
        if (_chunkPresetsWired) return;
        ChunkTargetField.AttachPresets(
            OllamaChunkTargetBox, OllamaChunkPresets,
            ResegmentTarget.MinChars, ResegmentTarget.OllamaMaxChars);
        ChunkTargetField.AttachPresets(
            OpenAiChunkTargetBox, OpenAiChunkPresets,
            ResegmentTarget.MinChars, ResegmentTarget.MaxChars);
        ChunkTargetField.AttachPresets(
            OpenRouterChunkTargetBox, OpenRouterChunkPresets,
            ResegmentTarget.MinChars, ResegmentTarget.MaxChars);
        ChunkTargetField.AttachPresets(
            CursorChunkTargetBox, CursorChunkPresets,
            ResegmentTarget.MinChars, ResegmentTarget.MaxChars);
        _chunkPresetsWired = true;
    }

    private static void BindChunkTarget(NumberBox box, string provider, int? stored)
    {
        box.Value = ResegmentTarget.Effective(stored, provider);
    }

    private NumberBox? TryChunkBox(string resourceId) => resourceId switch
    {
        "openai" => OpenAiChunkTargetBox,
        "openrouter" => OpenRouterChunkTargetBox,
        "cursor" => CursorChunkTargetBox,
        "ollama" => OllamaChunkTargetBox,
        _ => null,
    };

    private NumberBox ChunkBox(string resourceId) =>
        TryChunkBox(resourceId) ?? OllamaChunkTargetBox;

    private void SetChunkBox(string resourceId, int chars)
    {
        var box = TryChunkBox(resourceId);
        if (box is null) return;
        box.Value = ResegmentTarget.Clamp(
            chars, ResegmentTarget.MinChars, ResegmentTarget.MaxFor(resourceId));
    }

    private void WriteChunkTargetsFromUi()
    {
        if (_settings is null) return;
        foreach (var id in new[] { "ollama", "openai", "openrouter", "cursor" })
        {
            var resource = _settings.Models.Resources.FirstOrDefault(x => x.Id == id);
            if (resource is null) continue;
            var max = ResegmentTarget.MaxFor(resource.Provider);
            var chars = ChunkTargetField.ReadClamped(
                ChunkBox(id),
                ResegmentTarget.DefaultFor(resource.Provider),
                ResegmentTarget.MinChars,
                max);
            resource.ChunkTargetChars = ResegmentTarget.ToStored(chars, resource.Provider);
        }
    }

    private void BindListenSettings(AppSettings s)
    {
        s.Models.Tts ??= new TtsSettings();
        var tts = s.Models.Tts;
        ListenPreferences.SyncFromSettings(tts);
        SelectCombo(TtsRateBox, RateTag(ListenPreferences.Rate));
        BindSystemVoices(ListenPreferences.SystemVoiceId);
        UpdateListenVoiceHint();
    }

    private void RefreshListenVoices()
    {
        BindSystemVoices(ListenPreferences.SystemVoiceId);
        UpdateListenVoiceHint();
    }

    private void ApplyListenSettings()
    {
        if (_settings is null) return;
        var tts = _settings.Models.Tts ??= new TtsSettings();
        tts.Engine = "system";
        var rateTag = (TtsRateBox.SelectedItem as ComboBoxItem)?.Tag as string;
        if (double.TryParse(rateTag, NumberStyles.Float, CultureInfo.InvariantCulture, out var speed))
            tts.Speed = speed;
        if (TtsSystemVoiceBox.SelectedItem is ComboBoxItem voiceItem)
            ListenPreferences.SystemVoiceId = voiceItem.Tag as string ?? "";
        ListenPreferences.SyncFromSettings(tts);
    }

    private async void OpenSystemVoicePack_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            await Launcher.LaunchUriAsync(new Uri("ms-settings:speech"));
        }
        catch
        {
            StatusText.Text = "无法打开系统语音设置";
        }
    }

    private void UpdateListenVoiceHint()
    {
        var qualityNote = SystemNeuralEngine.HasDownloadedHighQualityVoice()
            ? "已检测到高质量系统语音，完全离线，不产生朗读费用。"
            : "未下载高质量语音包时听感接近机械音。";
        ListenPrivacyText.Text =
            qualityNote
            + " 下载由系统完成，Lumina 不代下音库。请添加「语音」里名称含 Neural 的神经语音，不要只下旁白 Natural（第三方用不了）。\n"
            + "1. 点下面的按钮打开系统语音设置\n"
            + "2. 添加语音 → 选中文或英文\n"
            + "3. 等待下载完成\n"
            + "4. 回到 Lumina，音色列表会刷新";
    }

    private static string RateTag(float rate)
    {
        var snapped = ListenPreferences.SnapRate(rate);
        if (Math.Abs(snapped - 1.0f) < 0.01) return "1";
        if (Math.Abs(snapped - 2.0f) < 0.01) return "2";
        return snapped.ToString("0.##", CultureInfo.InvariantCulture);
    }

    private void BindSystemVoices(string? selectedId)
    {
        TtsSystemVoiceBox.Items.Clear();
        TtsSystemVoiceBox.Items.Add(new ComboBoxItem { Content = "自动（高级优先）", Tag = "" });
        try
        {
            foreach (var voice in SpeechSynthesizer.AllVoices
                         .Where(v => v.Language.StartsWith("zh", StringComparison.OrdinalIgnoreCase)
                                     || v.Language.StartsWith("en", StringComparison.OrdinalIgnoreCase))
                         .OrderBy(v => v.Language).ThenBy(v => v.DisplayName))
            {
                TtsSystemVoiceBox.Items.Add(new ComboBoxItem
                {
                    Content = $"{voice.DisplayName} · {voice.Language} · {SystemNeuralEngine.QualityLabel(voice)}",
                    Tag = voice.Id,
                });
            }
        }
        catch
        {
            // Speech runtime missing; keep the automatic option.
        }
        var match = TtsSystemVoiceBox.Items.OfType<ComboBoxItem>()
            .FirstOrDefault(item => (item.Tag as string) == (selectedId ?? ""));
        TtsSystemVoiceBox.SelectedItem = match ?? TtsSystemVoiceBox.Items[0];
    }

    private void OnSidecarStateChanged()
    {
        DispatcherQueue.TryEnqueue(UpdateEngineRunStatus);
    }

    private void UpdateEngineRunStatus()
    {
        if (EngineRunStatusText is null) return;
        EngineRunStatusText.Text = App.Sidecar.EngineStatusLabel;
        EngineStopBtn.IsEnabled = App.Sidecar.IsRunning && !App.Sidecar.IsBootstrapping;
        EngineRestartBtn.IsEnabled = !App.Sidecar.IsBootstrapping;
    }

    private async void EngineStop_Click(object sender, RoutedEventArgs e)
    {
        EngineStopBtn.IsEnabled = false;
        EngineRestartBtn.IsEnabled = false;
        await App.Sidecar.StopAsync(userInitiated: true);
        UpdateEngineRunStatus();
        if (App.Sidecar.UserStopped)
            StatusText.Text = "引擎已停止";
    }

    private async void EngineRestart_Click(object sender, RoutedEventArgs e)
    {
        EngineStopBtn.IsEnabled = false;
        EngineRestartBtn.IsEnabled = false;
        StatusText.Text = "正在重启引擎…";
        await App.Sidecar.RestartAsync();
        UpdateEngineRunStatus();
        if (App.Sidecar.IsRunning)
            await LoadAsync();
        else
            StatusText.Text = App.Sidecar.LaunchError ?? "引擎未就绪";
    }
}
