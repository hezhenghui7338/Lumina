using System.Text.Json.Serialization;

namespace Lumina.Services;

public sealed class BookSummary
{
    public string Id { get; set; } = "";
    public string Title { get; set; } = "";
    public string Status { get; set; } = "";
    public int? SegmentCount { get; set; }
    public bool? IsFavorite { get; set; }
    public string? Category { get; set; }
    public string? LastOpenedAt { get; set; }
    public int? CurrentSegmentIndex { get; set; }
    public string? Author { get; set; }
    public int? SummaryReadyCount { get; set; }
    public int? SummaryTotalCount { get; set; }
    public string? SummarizeState { get; set; }

    [JsonIgnore]
    public int SummaryTotal => SummaryTotalCount ?? SegmentCount ?? 0;

    [JsonIgnore]
    public int SummaryReady => SummaryReadyCount ?? 0;

    [JsonIgnore]
    public string StatusLabel => Status switch
    {
        "unread" => "未读",
        "reading" => "在读",
        "summarized" => "已摘要",
        "processing" => "处理中",
        "error" => "导入失败",
        _ => Status,
    };

    [JsonIgnore]
    public string ProgressLabel
    {
        get
        {
            if (Status == "processing") return StatusLabel;
            var total = SummaryTotal;
            if (total <= 0) return StatusLabel;
            var ready = SummaryReady;
            if (ready >= total) return "已摘要";
            return $"{StatusLabel} · 摘要 {ready}/{total}";
        }
    }

    [JsonIgnore]
    public bool CanStartSummarize =>
        Status != "processing"
        && SummaryTotal > 0
        && SummaryReady < SummaryTotal
        && (SummarizeState is null or "idle" or "paused");

    [JsonIgnore]
    public bool CanStopSummarize =>
        Status != "processing"
        && SummarizeState is "running" or "queued" or "paused";
}

public sealed class OpenBookResponse
{
    public string Status { get; set; } = "";
    public int CurrentSegmentIndex { get; set; }
}

public sealed class SegmentRow
{
    public string Id { get; set; } = "";
    public int Idx { get; set; }
    public string? Label { get; set; }
    public string? Chapter { get; set; }
    public string SummaryStatus { get; set; } = "pending";
    public string? SummaryJson { get; set; }
    public string? RawText { get; set; }
    public string? Translation { get; set; }
    public string? AnchorLabel { get; set; }
    public int? CharCount { get; set; }

    [JsonIgnore]
    public string DisplayLabel =>
        !string.IsNullOrWhiteSpace(Label) ? Label! :
        !string.IsNullOrWhiteSpace(AnchorLabel) ? AnchorLabel! :
        $"段 {Idx + 1}";
}

public sealed class SegmentSummaryDetail
{
    public int Idx { get; set; }
    public string? SummaryJson { get; set; }
    public string? Label { get; set; }
    public string? AnchorLabel { get; set; }
    public string? SummaryStatus { get; set; }
}

public sealed class ChatCitation
{
    public int SegmentIndex { get; set; }
    public string Label { get; set; } = "";
}

public sealed class ChatResponse
{
    public string Answer { get; set; } = "";
    public List<ChatCitation> Citations { get; set; } = [];
    public bool? EvidenceSufficient { get; set; }
    public string? Provider { get; set; }
    public string? Model { get; set; }
    public int? DurationMs { get; set; }
    public double? Tps { get; set; }
}

public sealed class ChatMessage
{
    public Guid Id { get; } = Guid.NewGuid();
    public string Role { get; set; } = "";
    public string Content { get; set; } = "";
    public List<ChatCitation> Citations { get; set; } = [];
}

public sealed class AppSettings
{
    public string TargetLanguage { get; set; } = "zh-CN";
    public string WebSearchProvider { get; set; } = "ddgs";
    public string? TavilyApiKey { get; set; }
    public bool DebugMode { get; set; }
    public bool AutoStartSummary { get; set; }
    public ModelsSettings Models { get; set; } = new();
}

public sealed class ModelsSettings
{
    public List<ModelResourceSettings> Resources { get; set; } = [];
    public ProfileRouteSettings Chat { get; set; } = new();
    public ProfileRouteSettings Summarize { get; set; } = new();
}

public sealed class ProfileRouteSettings
{
    public List<string> Priority { get; set; } = [];
}

public sealed class ModelResourceSettings
{
    public string Id { get; set; } = "";
    public string Provider { get; set; } = "";
    public string BaseUrl { get; set; } = "";
    public string Model { get; set; } = "";
    public string? ApiKey { get; set; }
    public int? Concurrency { get; set; }
}

public sealed class OllamaStatus
{
    public bool Skipped { get; set; }
    public bool Installed { get; set; }
    public bool Served { get; set; }
    public bool ProbeOk { get; set; }
    public bool ModelReady { get; set; }
    public string Model { get; set; } = "";
    public string? Message { get; set; }
    public List<string> InstalledModels { get; set; } = [];

    [JsonIgnore]
    public bool Available => !Skipped && (ProbeOk || Served);
}

public sealed class ImportConflictException : Exception
{
    public string ExistingBookId { get; }
    public string BookTitle { get; }
    public string Path { get; }

    public ImportConflictException(string existingBookId, string title, string path)
        : base($"书已存在：{title}")
    {
        ExistingBookId = existingBookId;
        BookTitle = title;
        Path = path;
    }
}
