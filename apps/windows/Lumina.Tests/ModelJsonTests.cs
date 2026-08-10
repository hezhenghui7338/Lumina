using System.Net;
using System.Text;
using System.Text.Json;
using Lumina.Services;
using Xunit;

namespace Lumina.Tests;

public class ModelJsonTests
{
    private static readonly JsonSerializerOptions Opts = CoreClient.JsonOptions;

    [Fact]
    public void Deserializes_note_search_news_ops()
    {
        var noteJson = """{"id":"n1","book_id":"b1","segment_id":"s1","content":"hello","type":"manual","created_at":"2026-01-01","segment_index":2,"book_title":"Book"}""";
        var note = JsonSerializer.Deserialize<NoteRow>(noteJson, Opts)!;
        Assert.Equal("n1", note.Id);
        Assert.Equal("b1", note.BookId);
        Assert.Equal(2, note.SegmentIndex);

        var hitJson = """{"book_id":"b1","kind":"note","title":"t","snippet":"snip","segment_index":1,"note_id":"n1"}""";
        var hit = JsonSerializer.Deserialize<SearchHit>(hitJson, Opts)!;
        Assert.Equal("笔记", hit.KindLabel);
        Assert.Contains("n1", hit.Id);

        var briefJson = """{"date":"2026-08-10","count":1,"articles":[{"id":"a1","title":"News","url":"https://x","viewpoints":[],"quotes":[],"meta":{},"reasons":[]}]}""";
        var brief = JsonSerializer.Deserialize<NewsBrief>(briefJson, Opts)!;
        Assert.Equal(1, brief.Count);
        Assert.Equal("a1", brief.Articles[0].Id);

        var settingsJson = """{"target_language":"zh-CN","web_search_provider":"ddgs","debug_mode":true,"auto_start_summary":false,"models":{"resources":[{"id":"ollama","provider":"ollama","base_url":"http://127.0.0.1:11434","model":"qwen3.5:4b"}],"chat":{"priority":["ollama"]},"summarize":{"priority":["ollama"]}},"prompts":{"segment":"s","document":"d","chat":"c","news_chat":"nc","translate":"t","classify":"cl"},"prompts_defaults":{"segment":"","document":"","chat":"","news_chat":"","translate":"","classify":""}}""";
        var settings = JsonSerializer.Deserialize<AppSettings>(settingsJson, Opts)!;
        Assert.True(settings.DebugMode);
        Assert.Equal("ollama", settings.Models.Resources[0].Id);
        Assert.Equal("nc", settings.Prompts.NewsChat);
    }

    [Fact]
    public void SummaryJsonParser_reads_structured_fields()
    {
        var parsed = SummaryJsonParser.Parse("""{"three_sentence":"A. B. C.","key_points":["p1"],"watch_outs":["w1"],"follow_ups":["q1"]}""");
        Assert.Equal("A. B. C.", parsed.ThreeSentence);
        Assert.Equal(["p1"], parsed.KeyPoints);
        Assert.Equal(["w1"], parsed.WatchOuts);
        Assert.Equal(["q1"], parsed.FollowUps);
    }

    [Fact]
    public void SummarizeStateFilters_match_books()
    {
        var running = new BookSummary { SummarizeState = "running", SummaryTotalCount = 10, SummaryReadyCount = 1 };
        Assert.True(SummarizeStateFilters.Matches(SummarizeStateFilters.Running, running));
        Assert.False(SummarizeStateFilters.Matches(SummarizeStateFilters.Idle, running));
    }
}

public class CoreClientHttpTests
{
    [Fact]
    public async Task ListNotes_and_Search_hit_expected_paths()
    {
        var handler = new StubHandler(req =>
        {
            var path = req.RequestUri!.PathAndQuery;
            if (path.StartsWith("/notes", StringComparison.Ordinal))
            {
                return Json("""{"notes":[{"id":"n1","book_id":"b1","segment_id":"s1","content":"c","type":"manual","created_at":"t"}]}""");
            }
            if (path.StartsWith("/search", StringComparison.Ordinal))
            {
                Assert.Contains("q=hello", path);
                return Json("""{"results":[{"book_id":"b1","kind":"book","title":"Hello"}]}""");
            }
            if (path == "/books/categories")
            {
                return Json("""{"categories":["文学","科技"]}""");
            }
            if (path == "/ops/overview")
            {
                return Json("""{"task_counts":{"queued":1,"running":0,"completed":0,"failed":0,"cancelled":0},"job_queue":{"queue_depth":0,"active_jobs":[],"worker_count":0,"worker_target":0,"chat_preempted":false,"user_paused_all":false,"user_paused_books":[]},"resource_runtime":[]}""");
            }
            return new HttpResponseMessage(HttpStatusCode.NotFound);
        });

        using var client = new CoreClient(new Uri("http://127.0.0.1:17432/"), handler);
        var notes = await client.ListNotesAsync(bookId: "b1");
        Assert.Single(notes);
        var hits = await client.SearchAsync("hello");
        Assert.Equal("Hello", hits[0].Title);
        var cats = await client.ListBookCategoriesAsync();
        Assert.Equal(2, cats.Count);
        var ops = await client.FetchOpsOverviewAsync();
        Assert.Equal(1, ops.TaskCounts.Queued);
    }

    private static HttpResponseMessage Json(string body) =>
        new(HttpStatusCode.OK)
        {
            Content = new StringContent(body, Encoding.UTF8, "application/json"),
        };

    private sealed class StubHandler : HttpMessageHandler
    {
        private readonly Func<HttpRequestMessage, HttpResponseMessage> _fn;
        public StubHandler(Func<HttpRequestMessage, HttpResponseMessage> fn) => _fn = fn;
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
            => Task.FromResult(_fn(request));
    }
}
