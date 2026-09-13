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
    /// Background boot news (not part of the gate).
    public ColdStartPhaseState News { get; set; } = ColdStartPhaseState.Pending;
    public string? NewsDetail { get; set; }

    public static ColdStartPhaseSnapshot Initial => new();
}

public static class ColdStartReadiness
{
    public static readonly TimeSpan StatusPollInterval = TimeSpan.FromMilliseconds(100);

    public static readonly string[] GateRowKinds = ["engine", "data", "cache"];

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

    public static string RowLabel(
        string kind,
        ColdStartPhaseState state,
        string? cacheDetail = null) =>
        kind switch
        {
            "engine" => state == ColdStartPhaseState.Done ? "启动完毕" : "引擎启动中",
            "data" => state == ColdStartPhaseState.Done ? "准备完毕" : "数据准备中",
            "cache" when state == ColdStartPhaseState.Done => "加载完毕",
            "cache" when state == ColdStartPhaseState.Running && !string.IsNullOrWhiteSpace(cacheDetail) =>
                $"缓存加载中 · {cacheDetail}",
            "cache" => "缓存加载中",
            _ => "",
        };
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
