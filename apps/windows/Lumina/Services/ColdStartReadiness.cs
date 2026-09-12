namespace Lumina.Services;

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
    public ColdStartPhaseState News { get; set; } = ColdStartPhaseState.Pending;
    public string? NewsDetail { get; set; }

    public static ColdStartPhaseSnapshot Initial => new();
}

public static class ColdStartReadiness
{
    public static readonly TimeSpan StatusPollInterval = TimeSpan.FromMilliseconds(100);

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
        string? newsDetail) =>
        new()
        {
            Engine = engineDone ? ColdStartPhaseState.Done : ColdStartPhaseState.Running,
            Data = PhaseState(data),
            Cache = PhaseState(cache),
            News = PhaseState(news),
            NewsDetail = newsDetail,
        };

    public static bool IsProductReady(ColdStartPhaseSnapshot snapshot) =>
        snapshot.Engine == ColdStartPhaseState.Done
        && snapshot.Data == ColdStartPhaseState.Done
        && snapshot.Cache == ColdStartPhaseState.Done
        && (snapshot.News is ColdStartPhaseState.Done or ColdStartPhaseState.Failed);

    public static string RowLabel(string kind, ColdStartPhaseState state, bool newsFailed) =>
        kind switch
        {
            "engine" => state == ColdStartPhaseState.Done ? "启动完毕" : "引擎启动中",
            "data" => state == ColdStartPhaseState.Done ? "准备完毕" : "数据准备中",
            "cache" => state == ColdStartPhaseState.Done ? "加载完毕" : "缓存加载中",
            "news" when state == ColdStartPhaseState.Done => "更新完毕",
            "news" when state == ColdStartPhaseState.Failed || newsFailed => "更新完毕（未全部成功）",
            "news" => "资讯更新中",
            _ => "",
        };
}

public sealed class StartupStatusDto
{
    public string? Engine { get; set; }
    public string? Data { get; set; }
    public string? Cache { get; set; }
    public string? News { get; set; }
    public string? NewsDetail { get; set; }
}
