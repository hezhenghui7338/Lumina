namespace Lumina.Services;

using System.Text.Json.Serialization;

public enum ColdStartPhaseState
{
    Pending,
    Running,
    Done,
    Failed,
}

public sealed class ColdStartPhaseSnapshot
{
    public ColdStartPhaseState Engine { get; set; } = ColdStartPhaseState.Pending;
    public ColdStartPhaseState Data { get; set; } = ColdStartPhaseState.Pending;
    public ColdStartPhaseState Cache { get; set; } = ColdStartPhaseState.Pending;
    public double? CacheProgress { get; set; }
    public string? CacheDetail { get; set; }
    /// Background boot news (not part of product-ready).
    public ColdStartPhaseState News { get; set; } = ColdStartPhaseState.Pending;
    public string? NewsDetail { get; set; }

    public static ColdStartPhaseSnapshot Initial => new();
}

public static class ColdStartReadiness
{
    public static readonly TimeSpan StatusPollInterval = TimeSpan.FromMilliseconds(100);
    /// After this many seconds, reveal one soft technical line (PRD §3.5).
    public static readonly TimeSpan DetailRevealAfter = TimeSpan.FromSeconds(10);

    public static ColdStartPhaseState PhaseState(string? raw) =>
        (raw ?? "").ToLowerInvariant() switch
        {
            "running" => ColdStartPhaseState.Running,
            "done" => ColdStartPhaseState.Done,
            "failed" => ColdStartPhaseState.Failed,
            _ => ColdStartPhaseState.Pending,
        };

    public static ColdStartPhaseSnapshot Merge(
        bool engineDone,
        string? data,
        string? cache,
        string? news,
        string? newsDetail,
        double? cacheProgress = null,
        string? cacheDetail = null) =>
        new()
        {
            Engine = engineDone ? ColdStartPhaseState.Done : ColdStartPhaseState.Running,
            Data = PhaseState(data),
            Cache = PhaseState(cache),
            CacheProgress = cacheProgress,
            CacheDetail = cacheDetail,
            News = PhaseState(news),
            NewsDetail = newsDetail,
        };

    /// Product-ready after engine → data → cache (news is background).
    public static bool IsProductReady(ColdStartPhaseSnapshot snapshot) =>
        snapshot.Engine == ColdStartPhaseState.Done
        && snapshot.Data == ColdStartPhaseState.Done
        && snapshot.Cache == ColdStartPhaseState.Done;

    public static bool IsBootNewsTerminal(ColdStartPhaseState state) =>
        state is ColdStartPhaseState.Done or ColdStartPhaseState.Failed;

    public static bool ShouldRevealTechnicalDetail(TimeSpan elapsed) =>
        elapsed >= DetailRevealAfter;

    /// One soft line derived from the current internal phase (never a multi-step list).
    public static string TechnicalDetail(
        ColdStartPhaseSnapshot snapshot,
        string? launchError = null)
    {
        if (!string.IsNullOrWhiteSpace(launchError))
            return launchError;
        if (snapshot.Engine != ColdStartPhaseState.Done)
            return "正在启动引擎";
        if (snapshot.Data != ColdStartPhaseState.Done)
            return "正在准备阅读数据";
        if (!string.IsNullOrWhiteSpace(snapshot.CacheDetail))
            return snapshot.CacheDetail!;
        return "正在加载缓存";
    }
}

public sealed class StartupStatusDto
{
    [JsonPropertyName("engine")]
    public string? Engine { get; set; }

    [JsonPropertyName("data")]
    public string? Data { get; set; }

    [JsonPropertyName("cache")]
    public string? Cache { get; set; }

    [JsonPropertyName("cache_progress")]
    public double? CacheProgress { get; set; }

    [JsonPropertyName("cache_detail")]
    public string? CacheDetail { get; set; }

    [JsonPropertyName("news")]
    public string? News { get; set; }

    [JsonPropertyName("news_detail")]
    public string? NewsDetail { get; set; }
}
