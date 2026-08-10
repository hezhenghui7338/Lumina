using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Lumina.Services;

/// <summary>HTTP client for lumina-core. Network work stays off UI thread.</summary>
public sealed class CoreClient : IDisposable
{
    public static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };

    private readonly HttpClient _http;
    private readonly HttpClient _longHttp;
    private readonly Uri _baseUrl;
    private readonly bool _ownsClients;

    public CoreClient(Uri baseUrl)
    {
        _baseUrl = baseUrl;
        _http = new HttpClient { Timeout = TimeSpan.FromSeconds(60) };
        _longHttp = new HttpClient { Timeout = TimeSpan.FromMinutes(10) };
        _ownsClients = true;
    }

    /// <summary>Test / DI constructor sharing one handler for both clients.</summary>
    public CoreClient(Uri baseUrl, HttpMessageHandler handler)
    {
        _baseUrl = baseUrl;
        _http = new HttpClient(handler, disposeHandler: false) { Timeout = TimeSpan.FromSeconds(60) };
        _longHttp = new HttpClient(handler, disposeHandler: false) { Timeout = TimeSpan.FromMinutes(10) };
        _ownsClients = true;
    }

    public void Dispose()
    {
        if (!_ownsClients) return;
        _http.Dispose();
        _longHttp.Dispose();
    }

    // --- Books ---

    public async Task<IReadOnlyList<BookSummary>> ListBooksAsync(
        string filter = "all",
        string sort = "recent",
        CancellationToken ct = default)
    {
        var data = await GetAsync($"/books?filter={Uri.EscapeDataString(filter)}&sort={Uri.EscapeDataString(sort)}", ct)
            .ConfigureAwait(false);
        return Deserialize<BooksResp>(data)?.Books ?? [];
    }

    public async Task<IReadOnlyList<string>> ListBookCategoriesAsync(CancellationToken ct = default)
    {
        var data = await GetAsync("/books/categories", ct).ConfigureAwait(false);
        return Deserialize<CategoriesResp>(data)?.Categories ?? [];
    }

    public async Task<BookSummary> FetchBookAsync(string id, CancellationToken ct = default)
    {
        var data = await GetAsync($"/books/{id}", ct).ConfigureAwait(false);
        return Deserialize<BookSummary>(data) ?? new BookSummary { Id = id };
    }

    public async Task<BookSummary> UpdateBookAsync(
        string id,
        bool? isFavorite = null,
        string? category = null,
        string? title = null,
        CancellationToken ct = default)
    {
        var body = JsonSerializer.Serialize(new
        {
            is_favorite = isFavorite,
            category,
            title,
        }, JsonOptions);
        var data = await PatchAsync($"/books/{id}", body, ct).ConfigureAwait(false);
        return Deserialize<BookSummary>(data) ?? new BookSummary { Id = id };
    }

    public async Task DeleteBookAsync(string id, CancellationToken ct = default)
    {
        await SendEmptyAsync(HttpMethod.Delete, $"/books/{id}", ct).ConfigureAwait(false);
    }

    public async Task DeleteBooksAsync(IEnumerable<string> ids, CancellationToken ct = default)
    {
        foreach (var id in ids)
            await DeleteBookAsync(id, ct).ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<BookSummary>> SetBooksFavoriteAsync(
        IEnumerable<string> ids,
        bool isFavorite,
        CancellationToken ct = default)
    {
        var updated = new List<BookSummary>();
        foreach (var id in ids)
            updated.Add(await UpdateBookAsync(id, isFavorite: isFavorite, ct: ct).ConfigureAwait(false));
        return updated;
    }

    public async Task ClassifyBookAsync(string id, CancellationToken ct = default)
    {
        await PostAsync($"/books/{id}/classify", "{}", ct).ConfigureAwait(false);
    }

    public async Task<BookSummary> ImportBookAsync(string path, bool overwrite = false, CancellationToken ct = default)
    {
        var results = await ImportBooksAsync([path], overwrite, ct).ConfigureAwait(false);
        return results.FirstOrDefault()
            ?? throw new HttpRequestException("导入响应为空");
    }

    public async Task<IReadOnlyList<BookSummary>> ImportBooksAsync(
        IReadOnlyList<string> paths,
        bool overwrite = false,
        CancellationToken ct = default)
    {
        if (paths.Count == 0) return [];
        var body = JsonSerializer.Serialize(new { paths, overwrite }, JsonOptions);
        using var resp = await SendWithRetryAsync(HttpMethod.Post, "/books/import", body, ct).ConfigureAwait(false);
        var bytes = await resp.Content.ReadAsByteArrayAsync(ct).ConfigureAwait(false);
        if (resp.StatusCode == HttpStatusCode.Conflict)
            throw ParseImportConflict(bytes, paths[0]);
        EnsureSuccess(resp, bytes);
        var parsed = Deserialize<ImportResp>(bytes)
            ?? throw new HttpRequestException("导入响应无效");
        return parsed.Books.Select(b => new BookSummary
        {
            Id = b.BookId,
            Title = b.Title,
            Status = b.Status,
        }).ToList();
    }

    public async Task<OpenBookResponse> OpenBookAsync(string id, CancellationToken ct = default)
    {
        var data = await PostAsync($"/books/{id}/open", "{}", ct).ConfigureAwait(false);
        return Deserialize<OpenBookResponse>(data) ?? new OpenBookResponse();
    }

    public async Task SaveReadingProgressAsync(string bookId, int segmentIndex, CancellationToken ct = default)
    {
        var body = JsonSerializer.Serialize(new { segment_index = segmentIndex }, JsonOptions);
        await PatchAsync($"/books/{bookId}/reading-progress", body, ct).ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<SegmentRow>> ListSegmentsAsync(string bookId, CancellationToken ct = default)
    {
        var data = await GetLongAsync($"/books/{bookId}/segments", ct).ConfigureAwait(false);
        return Deserialize<SegmentsResp>(data)?.Segments ?? [];
    }

    public async Task<SegmentRow> GetSegmentAsync(string bookId, int idx, CancellationToken ct = default)
    {
        var data = await GetAsync($"/books/{bookId}/segments/{idx}", ct).ConfigureAwait(false);
        return Deserialize<SegmentRow>(data) ?? new SegmentRow { Idx = idx };
    }

    public async Task<SegmentSummaryDetail> FetchSegmentSummaryAsync(string bookId, int idx, CancellationToken ct = default)
    {
        var data = await GetAsync($"/books/{bookId}/segments/{idx}/summary", ct).ConfigureAwait(false);
        return Deserialize<SegmentSummaryDetail>(data) ?? new SegmentSummaryDetail { Idx = idx };
    }

    public async Task StartSummarizeAllAsync(CancellationToken ct = default)
    {
        await PostAsync("/books/summarize/start", "{}", ct).ConfigureAwait(false);
    }

    public async Task StopSummarizeAllAsync(CancellationToken ct = default)
    {
        await PostAsync("/books/summarize/stop", "{}", ct).ConfigureAwait(false);
    }

    public async Task StartSummarizeBooksAsync(IReadOnlyList<string> bookIds, CancellationToken ct = default)
    {
        var body = JsonSerializer.Serialize(new { book_ids = bookIds }, JsonOptions);
        await PostAsync("/books/summarize/start", body, ct).ConfigureAwait(false);
    }

    public async Task StopSummarizeBooksAsync(IReadOnlyList<string> bookIds, CancellationToken ct = default)
    {
        var body = JsonSerializer.Serialize(new { book_ids = bookIds }, JsonOptions);
        await PostAsync("/books/summarize/stop", body, ct).ConfigureAwait(false);
    }

    public async Task<SummarizeOverview> FetchSummarizeOverviewAsync(CancellationToken ct = default)
    {
        var data = await GetAsync("/books/summarize/overview", ct).ConfigureAwait(false);
        return Deserialize<SummarizeOverview>(data) ?? new SummarizeOverview();
    }

    public async Task StartSummarizeAsync(string bookId, CancellationToken ct = default)
    {
        await PostAsync($"/books/{bookId}/summarize/start", "{}", ct).ConfigureAwait(false);
    }

    public async Task StopSummarizeAsync(string bookId, CancellationToken ct = default)
    {
        await PostAsync($"/books/{bookId}/summarize/stop", "{}", ct).ConfigureAwait(false);
    }

    public async Task RetrySegmentAsync(string bookId, int idx, CancellationToken ct = default)
    {
        await PostAsync($"/books/{bookId}/segments/{idx}/retry", "{}", ct).ConfigureAwait(false);
    }

    public async Task RetrySegmentsAsync(string bookId, IReadOnlyList<int> indices, CancellationToken ct = default)
    {
        var body = JsonSerializer.Serialize(new { indices }, JsonOptions);
        await PostAsync($"/books/{bookId}/segments/retry", body, ct).ConfigureAwait(false);
    }

    public async Task RegenerateBookSummariesAsync(string bookId, CancellationToken ct = default)
    {
        await PostAsync($"/books/{bookId}/summarize/regenerate", "{}", ct).ConfigureAwait(false);
    }

    public async Task<string> ExportMarkdownAsync(string bookId, bool includeNotes = false, CancellationToken ct = default)
    {
        var body = JsonSerializer.Serialize(new { include_notes = includeNotes }, JsonOptions);
        var data = await PostAsync($"/books/{bookId}/export", body, ct).ConfigureAwait(false);
        return Encoding.UTF8.GetString(data);
    }

    // --- Chat ---

    public async Task<ChatResponse> ChatStreamAsync(
        string bookId,
        string message,
        int segmentIndex,
        Action<string> onToken,
        string? quote = null,
        CancellationToken ct = default)
    {
        var payload = new
        {
            message,
            segment_index = segmentIndex,
            stream = true,
            quote,
        };
        return await StreamChatAsync($"/books/{bookId}/chat", payload, onToken, includeCitations: true, ct)
            .ConfigureAwait(false);
    }

    public async Task<ChatResponse> NewsChatStreamAsync(
        string articleId,
        string message,
        Action<string> onToken,
        string? quote = null,
        CancellationToken ct = default)
    {
        var payload = new { message, stream = true, quote };
        return await StreamChatAsync($"/news/articles/{articleId}/chat", payload, onToken, includeCitations: false, ct)
            .ConfigureAwait(false);
    }

    // --- Notes ---

    public async Task<IReadOnlyList<NoteRow>> ListNotesAsync(
        string? bookId = null,
        string? segmentId = null,
        CancellationToken ct = default)
    {
        var q = new List<string>();
        if (!string.IsNullOrEmpty(bookId)) q.Add($"book_id={Uri.EscapeDataString(bookId)}");
        if (!string.IsNullOrEmpty(segmentId)) q.Add($"segment_id={Uri.EscapeDataString(segmentId)}");
        var path = q.Count == 0 ? "/notes" : "/notes?" + string.Join('&', q);
        var data = await GetAsync(path, ct).ConfigureAwait(false);
        return Deserialize<NotesResp>(data)?.Notes ?? [];
    }

    public async Task<NoteRow> CreateNoteAsync(
        string bookId,
        string content,
        string segmentId,
        string? quote = null,
        string type = "manual",
        CancellationToken ct = default)
    {
        var body = JsonSerializer.Serialize(new
        {
            book_id = bookId,
            content,
            segment_id = segmentId,
            quote,
            type,
        }, JsonOptions);
        var data = await PostAsync("/notes", body, ct).ConfigureAwait(false);
        return Deserialize<NoteRow>(data) ?? new NoteRow();
    }

    public async Task DeleteNoteAsync(string id, CancellationToken ct = default)
    {
        await SendEmptyAsync(HttpMethod.Delete, $"/notes/{id}", ct).ConfigureAwait(false);
    }

    public async Task DeleteNotesAsync(IEnumerable<string> ids, CancellationToken ct = default)
    {
        foreach (var id in ids)
            await DeleteNoteAsync(id, ct).ConfigureAwait(false);
    }

    // --- Search ---

    public async Task<IReadOnlyList<SearchHit>> SearchAsync(string query, CancellationToken ct = default)
    {
        var data = await GetAsync($"/search?q={Uri.EscapeDataString(query)}", ct).ConfigureAwait(false);
        return Deserialize<SearchResp>(data)?.Results ?? [];
    }

    // --- News ---

    public async Task<NewsBrief> FetchNewsBriefAsync(int limit = 25, CancellationToken ct = default)
    {
        var data = await GetAsync($"/news/brief?limit={limit}", ct).ConfigureAwait(false);
        return Deserialize<NewsBrief>(data) ?? new NewsBrief();
    }

    public async Task<IReadOnlyList<NewsSource>> FetchNewsSourcesAsync(CancellationToken ct = default)
    {
        var data = await GetAsync("/news/sources", ct).ConfigureAwait(false);
        return Deserialize<NewsSourcesResp>(data)?.Sources ?? [];
    }

    public async Task<NewsSource> AddNewsSourceAsync(string url, string title = "", CancellationToken ct = default)
    {
        var body = JsonSerializer.Serialize(new { url, title }, JsonOptions);
        var data = await PostAsync("/news/sources", body, ct).ConfigureAwait(false);
        return Deserialize<NewsSource>(data) ?? new NewsSource { Url = url, Title = title };
    }

    public async Task DeleteNewsSourceAsync(string id, CancellationToken ct = default)
    {
        await SendEmptyAsync(HttpMethod.Delete, $"/news/sources/{id}", ct).ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<NewsSource>> RestoreNewsDefaultsAsync(CancellationToken ct = default)
    {
        var data = await PostAsync("/news/sources/restore-defaults", "{}", ct).ConfigureAwait(false);
        return Deserialize<NewsSourcesRestoreResp>(data)?.Sources ?? [];
    }

    public async Task<IReadOnlyList<NewsSyncResult>> SyncNewsAsync(CancellationToken ct = default)
    {
        var data = await PostLongAsync("/news/sync", "{}", ct).ConfigureAwait(false);
        return Deserialize<NewsSyncResp>(data)?.Results ?? [];
    }

    public async Task<NewsArticleDetail> FetchNewsArticleAsync(string id, CancellationToken ct = default)
    {
        var data = await GetAsync($"/news/articles/{id}", ct).ConfigureAwait(false);
        return Deserialize<NewsArticleDetail>(data) ?? new NewsArticleDetail { Id = id };
    }

    public async Task<NewsReadResult> ReadNewsArticleAsync(
        string id,
        bool forceRefetch = false,
        bool skimOnly = false,
        CancellationToken ct = default)
    {
        var body = JsonSerializer.Serialize(new { force_refetch = forceRefetch, skim_only = skimOnly }, JsonOptions);
        var data = await PostLongAsync($"/news/articles/{id}/read", body, ct).ConfigureAwait(false);
        return Deserialize<NewsReadResult>(data) ?? new NewsReadResult();
    }

    // --- Settings ---

    public async Task<AppSettings> FetchSettingsAsync(CancellationToken ct = default)
    {
        var data = await GetAsync("/settings", ct).ConfigureAwait(false);
        return Deserialize<AppSettings>(data) ?? new AppSettings();
    }

    public async Task<AppSettings> UpdateSettingsAsync(AppSettings settings, CancellationToken ct = default)
    {
        var body = JsonSerializer.Serialize(new
        {
            target_language = settings.TargetLanguage,
            web_search_provider = settings.WebSearchProvider,
            tavily_api_key = settings.TavilyApiKey,
            debug_mode = settings.DebugMode,
            auto_start_summary = settings.AutoStartSummary,
            models = settings.Models,
            prompts = settings.Prompts,
        }, JsonOptions);
        var data = await PutAsync("/settings", body, ct).ConfigureAwait(false);
        return Deserialize<AppSettings>(data) ?? settings;
    }

    public async Task<OllamaStatus> FetchOllamaStatusAsync(string resourceId = "ollama", CancellationToken ct = default)
    {
        var data = await GetAsync($"/settings/ollama/status?resource_id={Uri.EscapeDataString(resourceId)}", ct)
            .ConfigureAwait(false);
        return Deserialize<OllamaStatus>(data) ?? new OllamaStatus();
    }

    public async Task<IReadOnlyList<ResourceStatus>> FetchAllResourceStatusAsync(CancellationToken ct = default)
    {
        var data = await GetAsync("/settings/resources/status", ct).ConfigureAwait(false);
        return Deserialize<ResourcesStatusResp>(data)?.Resources ?? [];
    }

    public async Task<ResourceStatus> FetchResourceStatusAsync(string resourceId, CancellationToken ct = default)
    {
        var data = await GetAsync($"/settings/resources/{Uri.EscapeDataString(resourceId)}/status", ct)
            .ConfigureAwait(false);
        return Deserialize<ResourceStatus>(data) ?? new ResourceStatus { ResourceId = resourceId };
    }

    // --- Ops ---

    public async Task<OpsOverview> FetchOpsOverviewAsync(CancellationToken ct = default)
    {
        var data = await GetAsync("/ops/overview", ct).ConfigureAwait(false);
        return Deserialize<OpsOverview>(data) ?? new OpsOverview();
    }

    public async Task<OpsTasksResponse> FetchOpsTasksAsync(string? status = null, CancellationToken ct = default)
    {
        var path = string.IsNullOrEmpty(status)
            ? "/ops/tasks"
            : $"/ops/tasks?status={Uri.EscapeDataString(status)}";
        var data = await GetAsync(path, ct).ConfigureAwait(false);
        return Deserialize<OpsTasksResponse>(data) ?? new OpsTasksResponse();
    }

    public async Task CancelOpsTaskAsync(string id, CancellationToken ct = default)
    {
        await PostAsync($"/ops/tasks/{id}/cancel", "{}", ct).ConfigureAwait(false);
    }

    public async Task<ResourceRuntimeResponse> FetchResourceRuntimeAsync(CancellationToken ct = default)
    {
        var data = await GetAsync("/ops/resources/runtime", ct).ConfigureAwait(false);
        return Deserialize<ResourceRuntimeResponse>(data) ?? new ResourceRuntimeResponse();
    }

    // --- Events ---

    public CancellationTokenSource SubscribeEvents(
        string bookId,
        Action<JsonElement> onEvent,
        CancellationToken externalCt = default)
    {
        var cts = CancellationTokenSource.CreateLinkedTokenSource(externalCt);
        _ = Task.Run(async () =>
        {
            try
            {
                using var req = new HttpRequestMessage(HttpMethod.Get, Url($"/books/{bookId}/events"));
                req.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("text/event-stream"));
                using var resp = await _http.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, cts.Token)
                    .ConfigureAwait(false);
                if (!resp.IsSuccessStatusCode) return;
                await using var stream = await resp.Content.ReadAsStreamAsync(cts.Token).ConfigureAwait(false);
                await foreach (var el in SseReader.ReadDataEventsAsync(stream, cts.Token).ConfigureAwait(false))
                    onEvent(el);
            }
            catch (OperationCanceledException) { }
            catch { /* caller refreshes */ }
        }, cts.Token);
        return cts;
    }

    // --- Internals ---

    private async Task<ChatResponse> StreamChatAsync(
        string path,
        object payload,
        Action<string> onToken,
        bool includeCitations,
        CancellationToken ct)
    {
        var body = JsonSerializer.Serialize(payload, JsonOptions);
        using var content = new StringContent(body, Encoding.UTF8, "application/json");
        using var req = new HttpRequestMessage(HttpMethod.Post, Url(path)) { Content = content };
        req.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("text/event-stream"));

        using var resp = await _http.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, ct)
            .ConfigureAwait(false);
        var errBytes = resp.IsSuccessStatusCode ? null : await resp.Content.ReadAsByteArrayAsync(ct).ConfigureAwait(false);
        if (!resp.IsSuccessStatusCode)
            EnsureSuccess(resp, errBytes ?? []);

        await using var stream = await resp.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);
        ChatResponse? final = null;
        var tokenBuffer = new StringBuilder();
        const int flushThreshold = 32;

        await foreach (var el in SseReader.ReadDataEventsAsync(stream, ct).ConfigureAwait(false))
        {
            if (!el.TryGetProperty("type", out var typeEl)) continue;
            var type = typeEl.GetString();
            if (type == "error")
            {
                var msg = el.TryGetProperty("message", out var m) ? m.GetString() : null;
                throw new HttpRequestException(msg ?? "深聊未完成（模型输出异常或上下文过长），请重试");
            }
            if (type == "token" && el.TryGetProperty("content", out var tok))
            {
                tokenBuffer.Append(tok.GetString());
                if (tokenBuffer.Length >= flushThreshold)
                {
                    onToken(tokenBuffer.ToString());
                    tokenBuffer.Clear();
                }
            }
            if (type == "done")
            {
                if (tokenBuffer.Length > 0)
                {
                    onToken(tokenBuffer.ToString());
                    tokenBuffer.Clear();
                }
                var citations = new List<ChatCitation>();
                if (includeCitations &&
                    el.TryGetProperty("citations", out var cites) &&
                    cites.ValueKind == JsonValueKind.Array)
                {
                    foreach (var c in cites.EnumerateArray())
                    {
                        citations.Add(new ChatCitation
                        {
                            SegmentIndex = c.TryGetProperty("segment_index", out var si) ? si.GetInt32() : 0,
                            Label = c.TryGetProperty("label", out var lb) ? lb.GetString() ?? "" : "",
                        });
                    }
                }
                final = new ChatResponse
                {
                    Answer = el.TryGetProperty("answer", out var ans) ? ans.GetString() ?? "" : "",
                    Citations = citations,
                    EvidenceSufficient = el.TryGetProperty("evidence_sufficient", out var es) && es.ValueKind == JsonValueKind.True,
                    Provider = el.TryGetProperty("provider", out var p) ? p.GetString() : null,
                    Model = el.TryGetProperty("model", out var mo) ? mo.GetString() : null,
                    DurationMs = el.TryGetProperty("duration_ms", out var d) && d.TryGetInt32(out var di) ? di : null,
                    PromptTokens = el.TryGetProperty("prompt_tokens", out var pt) && pt.TryGetInt32(out var pti) ? pti : null,
                    CompletionTokens = el.TryGetProperty("completion_tokens", out var ctEl) && ctEl.TryGetInt32(out var cti) ? cti : null,
                    TotalTokens = el.TryGetProperty("total_tokens", out var tt) && tt.TryGetInt32(out var tti) ? tti : null,
                    Tps = el.TryGetProperty("tps", out var t) && t.TryGetDouble(out var td) ? td : null,
                };
            }
        }

        if (tokenBuffer.Length > 0) onToken(tokenBuffer.ToString());
        return final ?? throw new HttpRequestException("深聊未完成（模型输出异常或上下文过长），请重试");
    }

    private Uri Url(string path) => new(_baseUrl, path);

    private async Task<byte[]> GetAsync(string path, CancellationToken ct)
    {
        using var resp = await SendWithRetryAsync(HttpMethod.Get, path, null, ct).ConfigureAwait(false);
        var data = await resp.Content.ReadAsByteArrayAsync(ct).ConfigureAwait(false);
        EnsureSuccess(resp, data);
        return data;
    }

    private async Task<byte[]> GetLongAsync(string path, CancellationToken ct)
    {
        using var resp = await _longHttp.GetAsync(Url(path), ct).ConfigureAwait(false);
        var data = await resp.Content.ReadAsByteArrayAsync(ct).ConfigureAwait(false);
        EnsureSuccess(resp, data);
        return data;
    }

    private async Task<byte[]> PostAsync(string path, string json, CancellationToken ct)
    {
        using var resp = await SendWithRetryAsync(HttpMethod.Post, path, json, ct).ConfigureAwait(false);
        var data = await resp.Content.ReadAsByteArrayAsync(ct).ConfigureAwait(false);
        EnsureSuccess(resp, data);
        return data;
    }

    private async Task<byte[]> PostLongAsync(string path, string json, CancellationToken ct)
    {
        using var content = new StringContent(json, Encoding.UTF8, "application/json");
        using var resp = await _longHttp.PostAsync(Url(path), content, ct).ConfigureAwait(false);
        var data = await resp.Content.ReadAsByteArrayAsync(ct).ConfigureAwait(false);
        EnsureSuccess(resp, data);
        return data;
    }

    private async Task<byte[]> PutAsync(string path, string json, CancellationToken ct)
    {
        using var resp = await SendWithRetryAsync(HttpMethod.Put, path, json, ct).ConfigureAwait(false);
        var data = await resp.Content.ReadAsByteArrayAsync(ct).ConfigureAwait(false);
        EnsureSuccess(resp, data);
        return data;
    }

    private async Task<byte[]> PatchAsync(string path, string json, CancellationToken ct)
    {
        using var resp = await SendWithRetryAsync(HttpMethod.Patch, path, json, ct).ConfigureAwait(false);
        var data = await resp.Content.ReadAsByteArrayAsync(ct).ConfigureAwait(false);
        EnsureSuccess(resp, data);
        return data;
    }

    private async Task SendEmptyAsync(HttpMethod method, string path, CancellationToken ct)
    {
        using var resp = await SendWithRetryAsync(method, path, null, ct).ConfigureAwait(false);
        var data = await resp.Content.ReadAsByteArrayAsync(ct).ConfigureAwait(false);
        EnsureSuccess(resp, data);
    }

    private async Task<HttpResponseMessage> SendWithRetryAsync(
        HttpMethod method,
        string path,
        string? jsonBody,
        CancellationToken ct)
    {
        Exception? last = null;
        for (var attempt = 1; attempt <= 5; attempt++)
        {
            try
            {
                using var req = new HttpRequestMessage(method, Url(path));
                if (jsonBody is not null)
                    req.Content = new StringContent(jsonBody, Encoding.UTF8, "application/json");
                return await _http.SendAsync(req, ct).ConfigureAwait(false);
            }
            catch (Exception ex) when (IsRetryable(ex) && attempt < 5)
            {
                last = ex;
                await Task.Delay(400, ct).ConfigureAwait(false);
            }
        }
        throw last ?? new HttpRequestException("连接失败");
    }

    private static bool IsRetryable(Exception ex) =>
        ex is HttpRequestException or TaskCanceledException;

    private static void EnsureSuccess(HttpResponseMessage resp, byte[] data)
    {
        if (resp.IsSuccessStatusCode) return;
        throw new HttpRequestException(HttpErrorMessage(data, (int)resp.StatusCode));
    }

    private static string HttpErrorMessage(byte[] data, int status)
    {
        try
        {
            using var doc = JsonDocument.Parse(data);
            if (doc.RootElement.TryGetProperty("detail", out var detail))
            {
                if (detail.ValueKind == JsonValueKind.String)
                    return detail.GetString() ?? $"HTTP {status}";
                if (detail.ValueKind == JsonValueKind.Object &&
                    detail.TryGetProperty("title", out var title))
                    return title.GetString() ?? $"HTTP {status}";
            }
        }
        catch { /* fall through */ }
        return Encoding.UTF8.GetString(data) is { Length: > 0 } s ? s : $"HTTP {status}";
    }

    private static ImportConflictException ParseImportConflict(byte[] data, string path)
    {
        try
        {
            using var doc = JsonDocument.Parse(data);
            if (doc.RootElement.TryGetProperty("detail", out var detail) &&
                detail.ValueKind == JsonValueKind.Object)
            {
                var id = detail.TryGetProperty("existing_book_id", out var bid) ? bid.GetString() ?? "" : "";
                var title = detail.TryGetProperty("title", out var t) ? t.GetString() ?? "未知书名" : "未知书名";
                return new ImportConflictException(id, title, path);
            }
        }
        catch { /* fall through */ }
        return new ImportConflictException("", "未知书名", path);
    }

    internal static T? Deserialize<T>(byte[] data) =>
        JsonSerializer.Deserialize<T>(data, JsonOptions);

    private sealed class BooksResp { public List<BookSummary> Books { get; set; } = []; }
    private sealed class CategoriesResp { public List<string> Categories { get; set; } = []; }
    private sealed class SegmentsResp { public List<SegmentRow> Segments { get; set; } = []; }
    private sealed class NotesResp { public List<NoteRow> Notes { get; set; } = []; }
    private sealed class SearchResp { public List<SearchHit> Results { get; set; } = []; }
    private sealed class NewsSourcesResp { public List<NewsSource> Sources { get; set; } = []; }
    private sealed class NewsSourcesRestoreResp { public List<NewsSource> Sources { get; set; } = []; }
    private sealed class NewsSyncResp { public List<NewsSyncResult> Results { get; set; } = []; }
    private sealed class ResourcesStatusResp { public List<ResourceStatus> Resources { get; set; } = []; }
    private sealed class ImportResp { public List<ImportResult> Books { get; set; } = []; }
    private sealed class ImportResult
    {
        public string BookId { get; set; } = "";
        public string Title { get; set; } = "";
        public string Status { get; set; } = "";
    }
}
