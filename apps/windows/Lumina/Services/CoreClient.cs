using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Lumina.Services;

/// <summary>HTTP client for lumina-core (P0 subset). Network work stays off UI thread.</summary>
public sealed class CoreClient
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };

    private readonly HttpClient _http;
    private readonly HttpClient _longHttp;
    private readonly Uri _baseUrl;

    public CoreClient(Uri baseUrl)
    {
        _baseUrl = baseUrl;
        _http = new HttpClient { Timeout = TimeSpan.FromSeconds(60) };
        _longHttp = new HttpClient
        {
            Timeout = TimeSpan.FromMinutes(10),
        };
    }

    public async Task<IReadOnlyList<BookSummary>> ListBooksAsync(
        string filter = "all",
        string sort = "recent",
        CancellationToken ct = default)
    {
        var data = await GetAsync($"/books?filter={Uri.EscapeDataString(filter)}&sort={Uri.EscapeDataString(sort)}", ct)
            .ConfigureAwait(false);
        var resp = Deserialize<BooksResp>(data);
        return resp?.Books ?? [];
    }

    public async Task<BookSummary> ImportBookAsync(string path, bool overwrite = false, CancellationToken ct = default)
    {
        var body = JsonSerializer.Serialize(new { paths = new[] { path }, overwrite }, JsonOptions);
        using var resp = await SendWithRetryAsync(HttpMethod.Post, "/books/import", body, ct).ConfigureAwait(false);
        var bytes = await resp.Content.ReadAsByteArrayAsync(ct).ConfigureAwait(false);
        if (resp.StatusCode == HttpStatusCode.Conflict)
            throw ParseImportConflict(bytes, path);
        EnsureSuccess(resp, bytes);
        var parsed = Deserialize<ImportResp>(bytes)
            ?? throw new HttpRequestException("导入响应无效");
        var first = parsed.Books.FirstOrDefault()
            ?? throw new HttpRequestException("导入响应为空");
        return new BookSummary
        {
            Id = first.BookId,
            Title = first.Title,
            Status = first.Status,
        };
    }

    public async Task DeleteBookAsync(string id, CancellationToken ct = default)
    {
        await SendEmptyAsync(HttpMethod.Delete, $"/books/{id}", ct).ConfigureAwait(false);
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
        var resp = Deserialize<SegmentsResp>(data);
        return resp?.Segments ?? [];
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

    public async Task StartSummarizeAsync(string bookId, CancellationToken ct = default)
    {
        await PostAsync($"/books/{bookId}/summarize/start", "{}", ct).ConfigureAwait(false);
    }

    public async Task StopSummarizeAsync(string bookId, CancellationToken ct = default)
    {
        await PostAsync($"/books/{bookId}/summarize/stop", "{}", ct).ConfigureAwait(false);
    }

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
        var body = JsonSerializer.Serialize(payload, JsonOptions);
        using var content = new StringContent(body, Encoding.UTF8, "application/json");
        using var req = new HttpRequestMessage(HttpMethod.Post, Url($"/books/{bookId}/chat")) { Content = content };
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
            if (el.TryGetProperty("type", out var typeEl))
            {
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
                    if (el.TryGetProperty("citations", out var cites) && cites.ValueKind == JsonValueKind.Array)
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
                        Tps = el.TryGetProperty("tps", out var t) && t.TryGetDouble(out var td) ? td : null,
                    };
                }
            }
        }

        if (tokenBuffer.Length > 0) onToken(tokenBuffer.ToString());
        return final ?? throw new HttpRequestException("深聊未完成（模型输出异常或上下文过长），请重试");
    }

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
                {
                    onEvent(el);
                }
            }
            catch (OperationCanceledException) { }
            catch { /* reconnect left to caller refresh */ }
        }, cts.Token);
        return cts;
    }

    public async Task<AppSettings> FetchSettingsAsync(CancellationToken ct = default)
    {
        var data = await GetAsync("/settings", ct).ConfigureAwait(false);
        return Deserialize<AppSettings>(data) ?? new AppSettings();
    }

    public async Task<AppSettings> UpdateSettingsAsync(AppSettings settings, CancellationToken ct = default)
    {
        var body = JsonSerializer.Serialize(settings, JsonOptions);
        var data = await PutAsync("/settings", body, ct).ConfigureAwait(false);
        return Deserialize<AppSettings>(data) ?? settings;
    }

    public async Task<OllamaStatus> FetchOllamaStatusAsync(CancellationToken ct = default)
    {
        var data = await GetAsync("/settings/ollama/status?resource_id=ollama", ct).ConfigureAwait(false);
        return Deserialize<OllamaStatus>(data) ?? new OllamaStatus();
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

    private async Task<byte[]> PutAsync(string path, string json, CancellationToken ct)
    {
        using var resp = await SendWithRetryAsync(HttpMethod.Put, path, json, ct).ConfigureAwait(false);
        var data = await resp.Content.ReadAsByteArrayAsync(ct).ConfigureAwait(false);
        EnsureSuccess(resp, data);
        return data;
    }

    private async Task PatchAsync(string path, string json, CancellationToken ct)
    {
        using var resp = await SendWithRetryAsync(HttpMethod.Patch, path, json, ct).ConfigureAwait(false);
        var data = await resp.Content.ReadAsByteArrayAsync(ct).ConfigureAwait(false);
        EnsureSuccess(resp, data);
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
        var msg = HttpErrorMessage(data, (int)resp.StatusCode);
        throw new HttpRequestException(msg);
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

    private static T? Deserialize<T>(byte[] data) =>
        JsonSerializer.Deserialize<T>(data, JsonOptions);

    private sealed class BooksResp
    {
        public List<BookSummary> Books { get; set; } = [];
    }

    private sealed class SegmentsResp
    {
        public List<SegmentRow> Segments { get; set; } = [];
    }

    private sealed class ImportResp
    {
        public List<ImportResult> Books { get; set; } = [];
    }

    private sealed class ImportResult
    {
        public string BookId { get; set; } = "";
        public string Title { get; set; } = "";
        public string Status { get; set; } = "";
    }
}
