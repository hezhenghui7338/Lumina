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

        var settingsJson = """{"target_language":"zh-CN","web_search_provider":"ddgs","web_search_enabled":true,"debug_mode":true,"auto_start_summary":false,"models":{"resources":[{"id":"ollama","provider":"ollama","base_url":"http://127.0.0.1:11434","model":"qwen3.5:4b","advanced_model":"qwen3.5:9b"}],"chat":{"priority":["ollama"]},"summarize":{"priority":["ollama"]}},"prompts":{"segment":"s","document":"d","chat":"c","news_chat":"nc","translate":"t","classify":"cl"},"prompts_defaults":{"segment":"","document":"","chat":"","news_chat":"","translate":"","classify":""}}""";
        var settings = JsonSerializer.Deserialize<AppSettings>(settingsJson, Opts)!;
        Assert.True(settings.DebugMode);
        Assert.True(settings.WebSearchEnabled);
        Assert.Equal("ollama", settings.Models.Resources[0].Id);
        Assert.Equal("qwen3.5:9b", settings.Models.Resources[0].AdvancedModel);
        var refJson = """{"title":"牛顿","url":"https://zh.wikipedia.org/wiki/牛顿","source":"Wikipedia"}""";
        var webRef = JsonSerializer.Deserialize<ChatWebRef>(refJson, Opts)!;
        Assert.Equal("牛顿", webRef.Title);
        Assert.Contains("[网]", webRef.DisplayTitle);
        Assert.NotNull(webRef.NavigateUri);
    }

    [Fact]
    public void Deserializes_context_probe_status()
    {
        var json = """{"resource_id":"ollama","status":"done","model":"qwen3.5:4b","current_chars":3500,"max_ok_chars":3500,"recommended_chars":2800,"steps":[{"chars":1500,"ok":true,"message":""}],"message":"实测后面内容仍被理解约 3500 字","waiting_for_slot":false}""";
        var status = JsonSerializer.Deserialize<ContextProbeStatus>(json, Opts)!;
        Assert.Equal("ollama", status.ResourceId);
        Assert.Equal("done", status.Status);
        Assert.Equal(2800, status.RecommendedChars);
        Assert.False(status.IsRunning);
        Assert.Contains("3500", status.DisplayMessage);
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
    public void Deserializes_segment_boundary_preview()
    {
        var json = """{"left_idx":2,"right_idx":3,"total_chars":900,"left_char_count":420,"candidates":[{"offset":210,"kind":"paragraph"},{"offset":420,"kind":"current"}],"oversized_limit":6000}""";
        var preview = JsonSerializer.Deserialize<SegmentBoundaryPreview>(json, Opts)!;
        Assert.Equal(2, preview.LeftIdx);
        Assert.Equal(2, preview.Candidates.Count);
        Assert.Equal(420, preview.Candidates[1].Offset);

        var movedJson = """{"left_idx":2,"right_idx":3,"left_char_count":630,"right_char_count":270,"left_status":"pending","right_status":"pending","oversized":false,"unchanged":false}""";
        var moved = JsonSerializer.Deserialize<SegmentBoundaryMoveResult>(movedJson, Opts)!;
        Assert.Equal(630, moved.LeftCharCount);
        Assert.False(moved.Unchanged);
    }

    [Fact]
    public void Deserializes_book_index_status()
    {
        var json = """{"id":"b1","title":"Sample","status":"summarized","segment_count":5,"summary_ready_count":5,"summary_total_count":5,"index_status":"ready"}""";
        var book = JsonSerializer.Deserialize<BookSummary>(json, Opts)!;
        Assert.Equal("ready", book.IndexStatus);
        Assert.True(book.CanChatBook);
        Assert.Equal("全书", book.BookChatLabel);
    }

    [Fact]
    public void SummarizeStateFilters_match_books()
    {
        var running = new BookSummary { SummarizeState = "running", SummaryTotalCount = 10, SummaryReadyCount = 1 };
        var queued = new BookSummary { SummarizeState = "queued", SummaryTotalCount = 10 };
        Assert.True(SummarizeStateFilters.Matches(SummarizeStateFilters.Running, running));
        Assert.True(SummarizeStateFilters.Matches(SummarizeStateFilters.Running, queued));
        Assert.False(SummarizeStateFilters.Matches(SummarizeStateFilters.Idle, running));
    }

    [Fact]
    public void LibraryCollections_match_reading_and_summary_buckets()
    {
        var unread = new BookSummary { Title = "A", SegmentCount = 10 };
        var reading = new BookSummary
        {
            Title = "B",
            SegmentCount = 10,
            LastOpenedAt = "2024-05-01T00:00:00Z",
            CurrentSegmentIndex = 2,
            SummarizeState = "idle",
        };
        var finished = new BookSummary
        {
            Title = "C",
            SegmentCount = 10,
            LastOpenedAt = "2024-06-01T00:00:00Z",
            CurrentSegmentIndex = 9,
            Status = "summarized",
        };
        var shortOpened = new BookSummary
        {
            Title = "D",
            SegmentCount = 1,
            LastOpenedAt = "2024-07-01T00:00:00Z",
            CurrentSegmentIndex = 0,
        };
        var summarizing = new BookSummary { Title = "E", SummarizeState = "queued", SegmentCount = 8 };

        Assert.True(LibraryCollections.Matches(LibraryCollections.Unread, unread));
        Assert.True(LibraryCollections.Matches(LibraryCollections.Reading, reading));
        Assert.True(LibraryCollections.Matches(LibraryCollections.Finished, finished));
        Assert.True(LibraryCollections.Matches(LibraryCollections.Reading, shortOpened));
        Assert.False(LibraryCollections.Matches(LibraryCollections.Finished, shortOpened));
        Assert.True(LibraryCollections.Matches(LibraryCollections.Summarizing, summarizing));
        Assert.Equal("段落数", LibrarySorts.Label(LibrarySorts.Segments));

        var sorted = LibrarySorts.Sorted([unread, reading, summarizing], LibrarySorts.Segments);
        Assert.Equal(["A", "B", "E"], sorted.Select(b => b.Title).ToList());
    }

    [Fact]
    public void ReadingProgressIndex_prefers_local_until_resegment()
    {
        Assert.Equal(6, ReadingProgressIndex.Restore(1, 6, 10, 10));
        Assert.Equal(0, ReadingProgressIndex.Restore(0, 8, 12, 4));
        Assert.Equal(9, ReadingProgressIndex.Restore(0, 99, 10, 10));
        Assert.Equal(3, ReadingProgressIndex.Restore(3, null, null, 10));
    }

    [Fact]
    public void ReadingProgressIndex_restore_offset_until_resegment()
    {
        Assert.Equal(120, ReadingProgressIndex.RestoreOffset(120, 10, 10));
        Assert.Equal(0, ReadingProgressIndex.RestoreOffset(120, 12, 4));
        Assert.Equal(0, ReadingProgressIndex.RestoreOffset(null, 10, 10));
    }

    [Fact]
    public void ReadingProgressIndex_should_commit_rejects_unconfirmed_jump_home()
    {
        Assert.False(ReadingProgressIndex.ShouldCommit(20, 0, false));
        Assert.True(ReadingProgressIndex.ShouldCommit(20, 0, true));
        Assert.True(ReadingProgressIndex.ShouldCommit(0, 0, false));
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
