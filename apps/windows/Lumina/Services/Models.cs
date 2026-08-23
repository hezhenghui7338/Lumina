using System.Text.Json.Serialization;

namespace Lumina.Services;

public enum SummaryTier
{
    Normal,
    Advanced,
}

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
    public string? CreatedAt { get; set; }
    public int? TotalCharCount { get; set; }
    public int? SummaryReadyCount { get; set; }
    public int? SummaryTotalCount { get; set; }
    public string? ChunkerVersion { get; set; }
    public string? Language { get; set; }
    public string? TargetLanguage { get; set; }
    public SummarizeActive? SummarizeActive { get; set; }
    public string? SummarizeState { get; set; }
    public int? SummarizeQueuedCount { get; set; }
    public string? SummaryTier { get; set; }
    public string? ProcessingKind { get; set; }
    public string? IndexStatus { get; set; }
    public string? IngestError { get; set; }

    [JsonIgnore]
    public bool Favorite => IsFavorite ?? false;

    [JsonIgnore]
    public string FavoriteMark => Favorite ? "★" : "";

    [JsonIgnore]
    public int SummaryTotal => SummaryTotalCount ?? SegmentCount ?? 0;

    [JsonIgnore]
    public int SummaryReady => SummaryReadyCount ?? 0;

    [JsonIgnore]
    public string StatusLabel
    {
        get
        {
            if (Status == "error")
            {
                var reason = IngestError?.Trim();
                return string.IsNullOrEmpty(reason) ? "导入失败" : $"导入失败：{reason}";
            }
            return Status switch
            {
                "unread" => "未读",
                "reading" => "在读",
                "summarized" => "已摘要",
                "processing" => "处理中",
                _ => Status,
            };
        }
    }

    [JsonIgnore]
    public int ReadingTotal => Math.Max(SegmentCount ?? 0, 0);

    [JsonIgnore]
    public int ReadingCurrent
    {
        get
        {
            if (LastOpenedAt is null || ReadingTotal <= 0) return 0;
            var index = Math.Clamp(CurrentSegmentIndex ?? 0, 0, ReadingTotal - 1);
            return index + 1;
        }
    }

    [JsonIgnore]
    public string ReadingStatusLabel
    {
        get
        {
            if (LastOpenedAt is null) return "未读";
            if (ReadingTotal <= 0) return "在读";
            if (ReadingTotal > 1 && ReadingCurrent >= ReadingTotal) return "已读完";
            return $"在读 · {ReadingCurrent}/{ReadingTotal} 段";
        }
    }

    [JsonIgnore]
    public string ReadingProgressBucket
    {
        get
        {
            if (LastOpenedAt is null) return "unread";
            if (ReadingTotal <= 1) return "reading";
            return ReadingCurrent >= ReadingTotal ? "finished" : "reading";
        }
    }

    [JsonIgnore]
    public string SegmentCountLabel
    {
        get
        {
            var n = SegmentCount ?? 0;
            return n > 0 ? $"{n} 段" : "未分段";
        }
    }

    [JsonIgnore]
    public string CoverInitial
    {
        get
        {
            var trimmed = Title?.Trim() ?? "";
            return trimmed.Length == 0 ? "书" : trimmed[..1];
        }
    }

    [JsonIgnore]
    public string CardStatusLine
    {
        get
        {
            if (Status == "processing") return StatusLabel;
            if (Status == "error") return StatusLabel;
            if (SummaryTotal > 0 && SummaryReady < SummaryTotal) return ProgressLabel;
            return ReadingStatusLabel;
        }
    }

    [JsonIgnore]
    public string ProgressLabel
    {
        get
        {
            if (Status == "processing") return StatusLabel;
            var total = SummaryTotal;
            if (total <= 0) return StatusLabel;
            var ready = SummaryReady;
            if (ready >= total) return ReadingStatusLabel;
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

    [JsonIgnore]
    public bool HasExportableSummary => SummaryReady > 0;

    [JsonIgnore]
    public bool CanChatBook =>
        SummaryTotal > 0 && SummaryReady >= SummaryTotal && IndexStatus == "ready";

    [JsonIgnore]
    public string BookChatLabel => IndexStatus switch
    {
        "ready" => "全书",
        "building" => "全书（索引生成中）",
        "error" => "全书（索引失败）",
        _ => SummaryReady >= SummaryTotal && SummaryTotal > 0 ? "全书（索引生成中）" : "全书",
    };
}

public sealed class SummarizeActive
{
    public int? SegmentIdx { get; set; }
    public string? Kind { get; set; }
    public double? ElapsedS { get; set; }
}

public sealed class SummarizeOverview
{
    public SummarizeOverviewCounts Counts { get; set; } = new();
    public bool UserPausedAll { get; set; }

    [JsonIgnore]
    public int ActiveCount => Counts.Running + Counts.Queued;
}

public sealed class SummarizeOverviewCounts
{
    public int Running { get; set; }
    public int Queued { get; set; }
    public int Paused { get; set; }
    public int Idle { get; set; }
    public int Summarized { get; set; }
}

public static class LibraryCollections
{
    public const string Recent = "recent";
    public const string Idle = "idle";
    public const string Summarizing = "summarizing";
    public const string Summarized = "summarized";
    public const string Unread = "unread";
    public const string Reading = "reading";
    public const string Finished = "finished";
    public const string Favorite = "favorite";

    public static readonly string[] FallbackCategories =
        ["文学", "历史", "科技", "哲学", "经济", "传记", "其他"];

    public static string Label(string raw) => raw switch
    {
        Recent or "all" => "最近",
        Idle => "未摘要",
        Summarizing => "摘要中",
        Summarized => "已摘要",
        Unread => "未读",
        Reading => "在读",
        Finished => "已读完",
        Favorite => "收藏",
        _ => raw,
    };

    public static bool Matches(string collection, BookSummary book) => collection switch
    {
        Recent or "all" => true,
        Idle => book.SummarizeState is "idle" or "paused",
        Summarizing => book.SummarizeState is "running" or "queued",
        Summarized => book.SummarizeState == "summarized"
            || (book.SummaryTotal > 0 && book.SummaryReady >= book.SummaryTotal),
        Unread => book.ReadingProgressBucket == "unread",
        Reading => book.ReadingProgressBucket == "reading",
        Finished => book.ReadingProgressBucket == "finished",
        Favorite => book.Favorite,
        _ => book.Category == collection,
    };
}

public static class LibraryFilters
{
    public const string All = "all";
    public static readonly string[] FallbackCategories = LibraryCollections.FallbackCategories;

    public static string Label(string raw) => LibraryCollections.Label(raw);
}

public static class LibrarySorts
{
    public const string Recent = "recent";
    public const string Added = "added";
    public const string Title = "title";
    public const string Segments = "segments";
    public const string Favorite = "favorite";

    public static string Label(string raw) => raw switch
    {
        "recent" => "最近访问",
        "added" => "添加时间",
        "title" => "标题",
        "segments" => "段落数",
        "favorite" => "收藏优先",
        _ => raw,
    };

    public static IReadOnlyList<BookSummary> Sorted(IEnumerable<BookSummary> books, string sort)
    {
        return sort switch
        {
            Added => books.OrderByDescending(b => b.CreatedAt ?? "").ToList(),
            Title => books.OrderBy(b => b.Title, StringComparer.CurrentCultureIgnoreCase).ToList(),
            Segments => books
                .OrderByDescending(b => b.SegmentCount ?? 0)
                .ThenBy(b => b.Title, StringComparer.CurrentCultureIgnoreCase)
                .ToList(),
            Favorite => books
                .OrderByDescending(b => b.Favorite)
                .ThenByDescending(b => b.LastOpenedAt ?? "")
                .ToList(),
            _ => books
                .OrderBy(b => b.LastOpenedAt is null)
                .ThenByDescending(b => b.LastOpenedAt ?? "")
                .ToList(),
        };
    }
}

public static class SummarizeStateFilters
{
    public const string All = "all";
    public const string Running = "running";
    public const string Idle = "idle";
    public const string Summarized = "summarized";

    public static string Label(string raw) => raw switch
    {
        "all" => "全部",
        "running" => "正在摘要",
        "idle" => "待摘要",
        "summarized" => "已摘要",
        _ => raw,
    };

    public static bool Matches(string filter, BookSummary book) => filter switch
    {
        Running => book.SummarizeState is "running" or "queued",
        Idle => book.SummarizeState is "idle" or "paused",
        Summarized => book.SummarizeState == "summarized"
            || (book.SummaryTotal > 0 && book.SummaryReady >= book.SummaryTotal),
        _ => true,
    };
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
    public string? SummaryProvider { get; set; }
    public string? SummaryModel { get; set; }
    public string? SummaryTier { get; set; }
    public int? CharCount { get; set; }
    public int? RetryCount { get; set; }
    public double? SummaryDurationS { get; set; }
    public int? SummaryLlmAttempts { get; set; }

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
    public string? SummaryProvider { get; set; }
    public string? SummaryModel { get; set; }
    public string? SummaryTier { get; set; }
    public double? SummaryDurationS { get; set; }
    public int? SummaryLlmAttempts { get; set; }
}

public sealed class SegmentBoundaryCandidate
{
    public int Offset { get; set; }
    public string Kind { get; set; } = "sentence";
}

public sealed class SegmentBoundaryPreview
{
    public int LeftIdx { get; set; }
    public int RightIdx { get; set; }
    public int TotalChars { get; set; }
    public int LeftCharCount { get; set; }
    public List<SegmentBoundaryCandidate> Candidates { get; set; } = [];
    public int OversizedLimit { get; set; }
}

public sealed class SegmentBoundaryMoveResult
{
    public int LeftIdx { get; set; }
    public int RightIdx { get; set; }
    public int LeftCharCount { get; set; }
    public int RightCharCount { get; set; }
    public string? LeftAnchorLabel { get; set; }
    public string? RightAnchorLabel { get; set; }
    public string? LeftChapter { get; set; }
    public string? RightChapter { get; set; }
    public string? LeftStatus { get; set; }
    public string? RightStatus { get; set; }
    public bool Oversized { get; set; }
    public bool Unchanged { get; set; }
    public int? OversizedLimit { get; set; }
}

public sealed class ChatCitation
{
    public int SegmentIndex { get; set; }
    public string Label { get; set; } = "";
}

public sealed class ChatWebRef
{
    public string Title { get; set; } = "";
    public string Url { get; set; } = "";
    public string? Source { get; set; }

    [JsonIgnore]
    public string DisplayTitle
    {
        get
        {
            var name = string.IsNullOrWhiteSpace(Title) ? Url : Title;
            return string.IsNullOrWhiteSpace(Source) ? $"[网] {name}" : $"[网] {name} · {Source}";
        }
    }

    [JsonIgnore]
    public Uri? NavigateUri => Uri.TryCreate(Url, UriKind.Absolute, out var uri) ? uri : null;
}

public sealed class ChatResponse
{
    public string Answer { get; set; } = "";
    public List<ChatCitation> Citations { get; set; } = [];
    public List<ChatWebRef> WebRefs { get; set; } = [];
    public bool? EvidenceSufficient { get; set; }
    public string? Provider { get; set; }
    public string? Model { get; set; }
    public int? DurationMs { get; set; }
    public int? PromptTokens { get; set; }
    public int? CompletionTokens { get; set; }
    public int? TotalTokens { get; set; }
    public double? Tps { get; set; }
}

public sealed class ChatMessage
{
    public Guid Id { get; } = Guid.NewGuid();
    public string Role { get; set; } = "";
    public string Content { get; set; } = "";
    public List<ChatCitation> Citations { get; set; } = [];
    public List<ChatWebRef> WebRefs { get; set; } = [];
    public string? Provider { get; set; }
    public string? Model { get; set; }
    public int? DurationMs { get; set; }
    public int? PromptTokens { get; set; }
    public int? CompletionTokens { get; set; }
    public int? TotalTokens { get; set; }
    public double? Tps { get; set; }

    public void ApplyMetrics(ChatResponse resp)
    {
        Provider = resp.Provider;
        Model = resp.Model;
        DurationMs = resp.DurationMs;
        PromptTokens = resp.PromptTokens;
        CompletionTokens = resp.CompletionTokens;
        TotalTokens = resp.TotalTokens;
        Tps = resp.Tps;
        WebRefs = resp.WebRefs;
    }
}

public sealed class NoteRow
{
    public string Id { get; set; } = "";
    public string BookId { get; set; } = "";
    public string SegmentId { get; set; } = "";
    public string? Quote { get; set; }
    public string Content { get; set; } = "";
    public string Type { get; set; } = "manual";
    public string CreatedAt { get; set; } = "";
    public int? SegmentIndex { get; set; }
    public string? SegmentLabel { get; set; }
    public string? BookTitle { get; set; }
}

public sealed class SearchHit
{
    public string BookId { get; set; } = "";
    public string? SegmentId { get; set; }
    public string? NoteId { get; set; }
    public string Kind { get; set; } = "";
    public string Title { get; set; } = "";
    public string? Snippet { get; set; }
    public int? SegmentIndex { get; set; }

    [JsonIgnore]
    public string Id => string.Join(':', BookId, SegmentId ?? "", NoteId ?? "", Kind);

    [JsonIgnore]
    public string KindLabel => Kind switch
    {
        "book" => "书籍",
        "segment" => "段落",
        "note" => "笔记",
        _ => Kind,
    };
}

public sealed class NewsArticleCard
{
    public string Id { get; set; } = "";
    public string Title { get; set; } = "";
    public string? Excerpt { get; set; }
    public string? OneLiner { get; set; }
    public string? Detail { get; set; }
    public List<string> Viewpoints { get; set; } = [];
    public List<string> Quotes { get; set; } = [];
    public Dictionary<string, string> Meta { get; set; } = new();
    public List<string> Reasons { get; set; } = [];
    public double? ScoreHint { get; set; }
    public string? SourceId { get; set; }
    public string? SourceTitle { get; set; }
    public string? Source { get; set; }
    public string Url { get; set; } = "";
    public string? PublishedAt { get; set; }
    public bool? SkimRich { get; set; }
    public string? SummaryStatus { get; set; }

    [JsonIgnore]
    public string DisplaySource => SourceTitle ?? Source ?? SourceId ?? "";

    [JsonIgnore]
    public bool NeedsLlmSkim
    {
        get
        {
            if (SkimRich == true) return false;
            if (Detail is { Length: >= 80 }) return false;
            if (Viewpoints.Count >= 2) return false;
            if (Quotes.Count > 0) return false;
            return true;
        }
    }
}

public sealed class NewsSource
{
    public string Id { get; set; } = "";
    public string Url { get; set; } = "";
    public string? Title { get; set; }
    public string? CreatedAt { get; set; }
    public bool? IsPreset { get; set; }

    [JsonIgnore]
    public bool Preset => IsPreset ?? false;

    [JsonIgnore]
    public string DisplayTitle =>
        !string.IsNullOrWhiteSpace(Title) ? Title! : Url;
}

public sealed class NewsBrief
{
    public string Date { get; set; } = "";
    public int Count { get; set; }
    public List<NewsArticleCard> Articles { get; set; } = [];
}

public sealed class NewsArticleDetail
{
    public string Id { get; set; } = "";
    public string Title { get; set; } = "";
    public string? Excerpt { get; set; }
    public string? OneLiner { get; set; }
    public string Url { get; set; } = "";
    public string? Author { get; set; }
    public string? PublishedAt { get; set; }
    public string? SummaryMarkdown { get; set; }
    public string? SummaryStatus { get; set; }
    public double? ScoreHint { get; set; }
}

public sealed class NewsReadResult
{
    public NewsArticleDetail Article { get; set; } = new();
    public string SummaryMarkdown { get; set; } = "";
    public List<string> Warnings { get; set; } = [];
    public string Error { get; set; } = "";
    public bool BodyComplete { get; set; } = true;
    public string? BodyText { get; set; }
}

public sealed class NewsSyncResult
{
    public string? SourceId { get; set; }
    public string? Status { get; set; }
    public int? Added { get; set; }
    public string? Error { get; set; }
}

public sealed class ResourceStatus
{
    public string ResourceId { get; set; } = "";
    public string Provider { get; set; } = "";
    public bool Ready { get; set; }
    public bool ProbeOk { get; set; }
    public bool KeyConfigured { get; set; }
    public bool ModelReady { get; set; }
    public string? Message { get; set; }
    public List<string>? AvailableModels { get; set; }
    public string? BaseUrl { get; set; }
    public bool? Installed { get; set; }
    public List<string>? InstalledModels { get; set; }
    public string? RamGb { get; set; }
    public bool? Skipped { get; set; }

    [JsonIgnore]
    public string DisplayMessage
    {
        get
        {
            var trimmed = Message?.Trim() ?? "";
            return string.IsNullOrEmpty(trimmed) ? (Ready ? "已就绪" : "未就绪") : trimmed;
        }
    }
}

public sealed class OpsTaskCounts
{
    public int Queued { get; set; }
    public int Running { get; set; }
    public int? Paused { get; set; }
    public int Completed { get; set; }
    public int Failed { get; set; }
    public int Cancelled { get; set; }
}

public sealed class OpsActiveJob
{
    public string BookId { get; set; } = "";
    public int SegmentIdx { get; set; }
    public string Kind { get; set; } = "";
    public string? JobKey { get; set; }

    [JsonIgnore]
    public string Id => JobKey ?? $"{BookId}-{SegmentIdx}-{Kind}";
}

public sealed class OpsJobQueueDiagnostics
{
    public int QueueDepth { get; set; }
    public List<OpsActiveJob> ActiveJobs { get; set; } = [];
    public int? PausedBacklogDepth { get; set; }
    public int WorkerCount { get; set; }
    public int WorkerTarget { get; set; }
    public bool ChatPreempted { get; set; }
    public bool UserPausedAll { get; set; }
    public List<string> UserPausedBooks { get; set; } = [];
}

public sealed class OpsLastCall
{
    public string? ResourceId { get; set; }
    public string? Profile { get; set; }
    public string? StartedAt { get; set; }
    public int? DurationMs { get; set; }
    public bool? Ok { get; set; }
    public string? Error { get; set; }
}

public sealed class ResourceRuntimeRow
{
    public string ResourceId { get; set; } = "";
    public int Limit { get; set; }
    public int InUse { get; set; }
    public int Available { get; set; }
    public ResourceStatus? Probe { get; set; }

    [JsonIgnore]
    public string Id => ResourceId;
}

public sealed class OpsOverview
{
    public OpsTaskCounts TaskCounts { get; set; } = new();
    public OpsJobQueueDiagnostics JobQueue { get; set; } = new();
    public List<ResourceRuntimeRow> ResourceRuntime { get; set; } = [];
    public OpsLastCall? LastCall { get; set; }
}

public sealed class OpsTask
{
    public string Id { get; set; } = "";
    public string Kind { get; set; } = "";
    public string Status { get; set; } = "";
    public string SubjectType { get; set; } = "";
    public string SubjectId { get; set; } = "";
    public string SubjectLabel { get; set; } = "";
    public string Detail { get; set; } = "";
    public string? ResourceId { get; set; }
    public string? Profile { get; set; }
    public string StartedAt { get; set; } = "";
    public string UpdatedAt { get; set; } = "";
    public string? Error { get; set; }
    public bool Cancellable { get; set; }
    public string? JobKey { get; set; }
    public int? LlmAttempt { get; set; }
    public int? MaxLlmAttempts { get; set; }
    public string? SummaryTier { get; set; }
    public double? DurationS { get; set; }
}

public sealed class OpsTasksResponse
{
    public List<OpsTask> Tasks { get; set; } = [];
    public OpsTaskCounts Counts { get; set; } = new();
}

public sealed class ResourceRuntimeResponse
{
    public List<ResourceRuntimeRow> Resources { get; set; } = [];
    public OpsLastCall? LastCall { get; set; }
}

public sealed class PromptsSettings
{
    public string Segment { get; set; } = "";
    public string? SegmentOllama { get; set; }
    public string? SegmentCloud { get; set; }
    public string Document { get; set; } = "";
    public string Chat { get; set; } = "";
    public string NewsChat { get; set; } = "";
    public string Translate { get; set; } = "";
    public string Classify { get; set; } = "";
}

public sealed class AppSettings
{
    public string TargetLanguage { get; set; } = "zh-CN";
    public string WebSearchProvider { get; set; } = "ddgs";
    public bool WebSearchEnabled { get; set; } = true;
    public string? TavilyApiKey { get; set; }
    public string OcrCloudBaseUrl { get; set; } = "";
    public string OcrCloudModel { get; set; } = "";
    public string? OcrCloudApiKey { get; set; }
    public double OcrCloudTimeoutSeconds { get; set; } = 60;
    public bool DebugMode { get; set; }
    public bool AutoStartSummary { get; set; }
    public ModelsSettings Models { get; set; } = new();
    public PromptsSettings Prompts { get; set; } = new();
    public PromptsSettings PromptsDefaults { get; set; } = new();
}

public sealed class OcrStatus
{
    public string Provider { get; set; } = "local";
    public bool Ready { get; set; }
    public bool ProbeOk { get; set; }
    public bool Configured { get; set; }
    public bool KeyConfigured { get; set; }
    public bool ModelReady { get; set; }
    public string? Message { get; set; }
    public string? BaseUrl { get; set; }

    [JsonIgnore]
    public string DisplayMessage => string.IsNullOrWhiteSpace(Message)
        ? (Ready ? "已就绪" : "未就绪")
        : Message;
}

public sealed class ContextProbeStep
{
    public int Chars { get; set; }
    public bool Ok { get; set; }
    public string? Message { get; set; }
}

public sealed class ContextProbeStatus
{
    public string ResourceId { get; set; } = "";
    public string Status { get; set; } = "idle";
    public string? Model { get; set; }
    public int? CurrentChars { get; set; }
    public int? MaxOkChars { get; set; }
    public int? RecommendedChars { get; set; }
    public List<ContextProbeStep> Steps { get; set; } = [];
    public string? Message { get; set; }
    public bool WaitingForSlot { get; set; }

    [JsonIgnore]
    public bool IsRunning => Status == "running";

    [JsonIgnore]
    public string DisplayMessage
    {
        get
        {
            if (!string.IsNullOrWhiteSpace(Message)) return Message;
            return Status switch
            {
                "running" => "正在测试后面的段是否仍被理解…",
                "done" => "测试完成",
                "cancelled" => "已取消",
                "failed" => "测试失败",
                _ => "",
            };
        }
    }
}

public sealed class ModelsSettings
{
    public List<ModelResourceSettings> Resources { get; set; } = [];
    public ProfileRouteSettings Chat { get; set; } = new();
    public ProfileRouteSettings Summarize { get; set; } = new();
    public ProfileRouteSettings? Translate { get; set; }
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
    public string? AdvancedModel { get; set; }
    public string? ApiKey { get; set; }
    public double? ChatTimeout { get; set; }
    public int? Concurrency { get; set; }
    public int? ChunkTargetChars { get; set; }
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

/// <summary>Parsed structured segment summary for reader UI.</summary>
public sealed class StructuredSummary
{
    public string? ThreeSentence { get; set; }
    public List<string> KeyPoints { get; set; } = [];
    public List<string> WatchOuts { get; set; } = [];
    public List<string> FollowUps { get; set; } = [];
    public string? RawFallback { get; set; }
}

public static class ReadingProgressIndex
{
    public static int Restore(
        int serverIndex,
        int? localIndex,
        int? localSegmentCount,
        int currentSegmentCount)
    {
        var last = Math.Max(currentSegmentCount - 1, 0);
        if (localIndex is int local && localSegmentCount == currentSegmentCount && currentSegmentCount > 0)
            return Math.Clamp(local, 0, last);
        return Math.Clamp(serverIndex, 0, last);
    }

    public static double RestoreOffset(
        double? localOffset,
        int? localSegmentCount,
        int currentSegmentCount)
    {
        if (localSegmentCount == currentSegmentCount && currentSegmentCount > 0)
            return Math.Max(0, localOffset ?? 0);
        return 0;
    }

    /// Reject a jump to segment 0 unless the viewport really contains it.
    public static bool ShouldCommit(int? previousIndex, int nextIndex, bool hitContained)
    {
        if (nextIndex == 0 && previousIndex is int prev && prev > 0 && !hitContained)
            return false;
        return true;
    }
}
