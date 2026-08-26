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

        var originalJson = """{"query":"学而","hits":[{"segment_index":4,"start":10,"end":12,"start_utf16":10,"end_utf16":12,"snippet":"子曰：[学而]时习"}],"truncated":false}""";
        var original = JsonSerializer.Deserialize<OriginalSearchResponse>(originalJson, Opts)!;
        Assert.Equal("学而", original.Query);
        Assert.Single(original.Hits);
        Assert.Equal(4, original.Hits[0].SegmentIndex);
        Assert.Equal(10, original.Hits[0].StartUtf16);
        Assert.False(original.Truncated);

        var briefJson = """{"date":"2026-08-10","count":1,"articles":[{"id":"a1","title":"News","url":"https://x","viewpoints":[],"quotes":[],"meta":{},"reasons":[]}]}""";
        var brief = JsonSerializer.Deserialize<NewsBrief>(briefJson, Opts)!;
        Assert.Equal(1, brief.Count);
        Assert.Equal("a1", brief.Articles[0].Id);

        var settingsJson = """{"target_language":"zh-CN","web_search_provider":"ddgs","web_search_enabled":true,"debug_mode":true,"auto_start_summary":false,"models":{"resources":[{"id":"ollama","provider":"ollama","base_url":"http://127.0.0.1:11434","model":"qwen3.5:4b","advanced_model":"qwen3.5:9b"}],"chat":{"priority":["ollama"]},"summarize":{"priority":["ollama"]}},"prompts":{"segment":"s","document":"d","chat":"c","news_chat":"nc","translate":"t","classify":"cl"},"prompts_defaults":{"segment":"","document":"","chat":"","news_chat":"","translate":"","classify":""}}""";
        var settings = JsonSerializer.Deserialize<AppSettings>(settingsJson, Opts)!;
        Assert.True(settings.DebugMode);
        Assert.False(settings.AutoStartSummary);
        Assert.Equal("normal", settings.DefaultSegmentTier);
        Assert.True(settings.WebSearchEnabled);
        Assert.Equal("ollama", settings.Models.Resources[0].Id);
        Assert.Equal("qwen3.5:9b", settings.Models.Resources[0].AdvancedModel);
        Assert.Equal("system", settings.Models.Tts.Engine);
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
    public void Deserializes_segment_summary_preview_without_json()
    {
        var json = """{"id":"s1","idx":0,"summary_status":"ready","summary_preview":"邻里虽敬其向学，却无力资助书卷。","label":"邻里虽敬","chapter":"第一章","bullet_labels":["邻里","赴考"]}""";
        var row = JsonSerializer.Deserialize<SegmentRow>(json, Opts)!;
        Assert.Equal("邻里虽敬其向学，却无力资助书卷。", row.SummaryPreview);
        Assert.Null(row.SummaryJson);
        Assert.Equal("邻里虽敬", row.Label);
        Assert.Equal(new[] { "邻里", "赴考" }, row.BulletLabels);
        Assert.Equal("第一章 · 段 1 · 邻里虽敬", row.CatalogHeadline);
        Assert.Equal("邻里 · 赴考", row.BulletLabelsLine);
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
    public void SummarizeOverview_indexing_stall_never_reads_as_zero_running()
    {
        var json = """{"counts":{"running":0,"queued":3,"paused":0,"idle":0,"summarized":9,"indexing":1},"indexing_queued":2,"stalled_reason":"indexing","user_paused_all":false}""";
        var overview = JsonSerializer.Deserialize<SummarizeOverview>(json, Opts)!;
        Assert.Equal(1, overview.Counts.Indexing);
        Assert.Equal(2, overview.IndexingQueued);
        Assert.Equal("indexing", overview.StalledReason);
        Assert.Equal(4, overview.ActiveCount);
        Assert.Equal("3 排队 · 1 建索引 · 正在建索引", overview.StatusLine);
        Assert.DoesNotContain("0 进行中", overview.StatusLine);
    }

    [Fact]
    public void SummarizeOverview_decodes_legacy_payload_without_indexing_fields()
    {
        var json = """{"counts":{"running":1,"queued":2,"paused":0,"idle":0,"summarized":3},"user_paused_all":false}""";
        var overview = JsonSerializer.Deserialize<SummarizeOverview>(json, Opts)!;
        Assert.Equal(0, overview.Counts.Indexing);
        Assert.Equal(3, overview.ActiveCount);
        Assert.Null(overview.StalledReason);
        Assert.Equal("1 进行中 · 2 排队", overview.StatusLine);
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
            ReadingPercent = 1.0,
        };
        var shortOpened = new BookSummary
        {
            Title = "D",
            SegmentCount = 1,
            LastOpenedAt = "2024-07-01T00:00:00Z",
            CurrentSegmentIndex = 0,
        };
        var summarizing = new BookSummary { Title = "E", SummarizeState = "queued", SegmentCount = 8 };
        var segmenting = new BookSummary
        {
            Title = "F",
            Status = "processing",
            SummarizeState = "segmenting",
            SegmentCount = 0,
        };
        var resegmentWasDone = new BookSummary
        {
            Title = "G",
            Status = "processing",
            SummarizeState = "segmenting",
            SegmentCount = 10,
            SummaryReadyCount = 10,
            SummaryTotalCount = 10,
        };

        Assert.True(LibraryCollections.Matches(LibraryCollections.Unread, unread));
        Assert.True(LibraryCollections.Matches(LibraryCollections.Reading, reading));
        Assert.True(LibraryCollections.Matches(LibraryCollections.Finished, finished));
        Assert.True(LibraryCollections.Matches(LibraryCollections.Reading, shortOpened));
        Assert.False(LibraryCollections.Matches(LibraryCollections.Finished, shortOpened));
        Assert.True(LibraryCollections.Matches(LibraryCollections.Summarizing, summarizing));
        Assert.True(LibraryCollections.Matches(LibraryCollections.Segmenting, segmenting));
        Assert.True(LibraryCollections.Matches(LibraryCollections.Segmenting, resegmentWasDone));
        Assert.False(LibraryCollections.Matches(LibraryCollections.Summarized, resegmentWasDone));
        Assert.False(LibraryCollections.Matches(LibraryCollections.Idle, segmenting));
        Assert.Equal("分段中", LibraryCollections.Label(LibraryCollections.Segmenting));
        Assert.Equal("分段中", segmenting.StatusLabel);
        Assert.Equal("分段中", segmenting.CardStatusLine);
        var ingesting = new BookSummary
        {
            Title = "大TXT",
            Status = "processing",
            SegmentCount = 0,
            IngestMessage = "正在识别序言与正文结构…",
            IngestPage = 1,
            IngestTotal = 4,
        };
        Assert.Contains("正在识别序言与正文结构", ingesting.CardStatusLine, StringComparison.Ordinal);
        Assert.Contains("%", ingesting.CardStatusLine, StringComparison.Ordinal);

        var ingestFailed = new BookSummary
        {
            Title = "坏书",
            Status = "error",
            SegmentCount = 0,
            SummarizeState = "summarized",
            IngestError = "unknown encoding",
        };
        var ingestCancelled = new BookSummary
        {
            Title = "取消",
            Status = "error",
            SegmentCount = 0,
            SummarizeState = "idle",
            IngestError = "已取消导入",
        };
        Assert.True(LibraryCollections.Matches(LibraryCollections.IngestFailed, ingestFailed));
        Assert.True(LibraryCollections.Matches(LibraryCollections.IngestFailed, ingestCancelled));
        Assert.False(LibraryCollections.Matches(LibraryCollections.Summarized, ingestFailed));
        Assert.False(LibraryCollections.Matches(LibraryCollections.Idle, ingestCancelled));
        var hole = new BookSummary
        {
            Title = "空档",
            Status = "unread",
            SegmentCount = 0,
            SummaryReadyCount = 0,
            SummaryTotalCount = 0,
            SummarizeState = "summarized",
        };
        Assert.True(hole.IsSegmenting);
        Assert.Equal("分段中", hole.SummaryFacetLabel);
        Assert.Equal("分段中", hole.CardStatusLine);
        Assert.True(LibraryCollections.Matches(LibraryCollections.Segmenting, hole));
        Assert.False(LibraryCollections.Matches(LibraryCollections.Idle, hole));
        Assert.False(LibraryCollections.Matches(LibraryCollections.Summarized, hole));
        Assert.False(LibraryCollections.Matches(LibraryCollections.IngestFailed, hole));
        Assert.Equal("导入失败", LibraryCollections.Label(LibraryCollections.IngestFailed));
        Assert.True(LibraryFacets.Matches(ingestFailed, LibraryCollections.IngestFailed, LibraryFacets.All, LibraryFacets.All));
        Assert.False(LibraryFacets.Matches(ingestFailed, LibraryCollections.Summarized, LibraryFacets.All, LibraryFacets.All));
        Assert.Equal("导入失败", LibraryCollections.Label(LibraryCollections.IngestFailed));
        Assert.Equal("导入失败", LibraryFacets.Title(LibraryCollections.IngestFailed, LibraryFacets.All, LibraryFacets.All, false));
        Assert.Equal("段落数", LibrarySorts.Label(LibrarySorts.Segments));
        Assert.Equal("阅读进度", LibrarySorts.Label(LibrarySorts.Progress));

        var sorted = LibrarySorts.Sorted([unread, reading, summarizing], LibrarySorts.Segments);
        Assert.Equal(["A", "B", "E"], sorted.Select(b => b.Title).ToList());

        var byProgress = LibrarySorts.Sorted(
            [unread, reading, finished, shortOpened],
            LibrarySorts.Progress);
        Assert.Equal(["C", "B", "A", "D"], byProgress.Select(b => b.Title).ToList());
    }

    [Fact]
    public void Empty_unread_book_is_segmenting_not_summarized()
    {
        var hole = new BookSummary
        {
            Title = "空档",
            Status = "unread",
            SegmentCount = 0,
            SummaryReadyCount = 0,
            SummaryTotalCount = 0,
            SummarizeState = "summarized",
        };
        Assert.True(hole.IsSegmenting);
        Assert.True(hole.CanOpenInReader);
        Assert.Equal("分段中", hole.SummaryFacetLabel);
        Assert.Equal("分段中", hole.CardStatusLine);
        Assert.True(LibraryCollections.Matches(LibraryCollections.Segmenting, hole));
        Assert.False(LibraryCollections.Matches(LibraryCollections.Idle, hole));
        Assert.False(LibraryCollections.Matches(LibraryCollections.Summarized, hole));
        Assert.False(LibraryCollections.Matches(LibraryCollections.IngestFailed, hole));
        Assert.True(LibraryFacets.MatchesSummary(LibraryCollections.Segmenting, hole));
    }

    [Fact]
    public void LibraryFacets_default_to_all_and_combine_with_and()
    {
        var hit = new BookSummary
        {
            Title = "史记",
            SegmentCount = 10,
            SummarizeState = "summarized",
            Category = "历史",
            SummaryReadyCount = 10,
            SummaryTotalCount = 10,
        };
        var wrongCategory = new BookSummary
        {
            Title = "黑客与画家",
            SegmentCount = 10,
            SummarizeState = "summarized",
            Category = "科技",
            SummaryReadyCount = 10,
            SummaryTotalCount = 10,
        };
        var idle = new BookSummary
        {
            Title = "未摘要",
            SegmentCount = 10,
            SummarizeState = "idle",
            Category = "历史",
        };
        var opened = new BookSummary
        {
            Title = "在读史书",
            SegmentCount = 10,
            SummarizeState = "summarized",
            Category = "历史",
            LastOpenedAt = "2024-05-01T00:00:00Z",
            CurrentSegmentIndex = 2,
            SummaryReadyCount = 10,
            SummaryTotalCount = 10,
        };

        Assert.True(LibraryFacets.IsDefault(LibraryFacets.All, LibraryFacets.All, LibraryFacets.All, false));
        Assert.Equal("书架", LibraryFacets.Title(LibraryFacets.All, LibraryFacets.All, LibraryFacets.All, false));
        Assert.True(LibraryFacets.Matches(hit, LibraryCollections.Summarized, LibraryCollections.Unread, "历史"));
        Assert.False(LibraryFacets.Matches(wrongCategory, LibraryCollections.Summarized, LibraryCollections.Unread, "历史"));
        Assert.False(LibraryFacets.Matches(idle, LibraryCollections.Summarized, LibraryCollections.Unread, "历史"));
        Assert.False(LibraryFacets.Matches(opened, LibraryCollections.Summarized, LibraryCollections.Unread, "历史"));
        Assert.Equal(
            "已摘要 · 未读 · 历史",
            LibraryFacets.Title(LibraryCollections.Summarized, LibraryCollections.Unread, "历史", false));
        Assert.Equal("分段中", LibraryFacets.Title(LibraryCollections.Segmenting, LibraryFacets.All, LibraryFacets.All, false));
        Assert.True(LibraryFacets.Matches(
            new BookSummary { Status = "processing", SummarizeState = "segmenting" },
            LibraryCollections.Segmenting));
        Assert.Equal("全部", LibraryCollections.Label(LibraryFacets.All));
    }

    [Fact]
    public void BookCoverPalette_tints_by_category()
    {
        Assert.Equal((184, 97, 82), BookCoverPalette.Rgb("文学"));
        Assert.Equal((140, 107, 71), BookCoverPalette.Rgb("历史"));
        Assert.Equal((71, 115, 158), BookCoverPalette.Rgb("科技"));
        Assert.Equal((107, 92, 148), BookCoverPalette.Rgb("哲学"));
        Assert.Equal((71, 133, 107), BookCoverPalette.Rgb("经济"));
        Assert.Equal((158, 107, 71), BookCoverPalette.Rgb("传记"));
        Assert.Equal((115, 117, 128), BookCoverPalette.Rgb(null));
        Assert.Equal((115, 117, 128), BookCoverPalette.Rgb("其他"));
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
    public void ReadingProgressIndex_restore_offset_when_segment_count_matches()
    {
        Assert.Equal(120, ReadingProgressIndex.RestoreOffset(120, 10, 10));
        Assert.Equal(0, ReadingProgressIndex.RestoreOffset(120, 12, 4));
        Assert.Equal(0, ReadingProgressIndex.RestoreOffset(null, 10, 10));
    }

    [Fact]
    public void ReadingProgressIndex_should_commit_rejects_unconfirmed_jump_home()
    {
        Assert.False(ReadingProgressIndex.ShouldCommit(20, 0, false));
        Assert.False(ReadingProgressIndex.ShouldCommit(20, 0, true));
        Assert.True(ReadingProgressIndex.ShouldCommit(20, 0, true, true));
        Assert.True(ReadingProgressIndex.ShouldCommit(0, 0, false));
    }

    [Fact]
    public void ReadingProgressIndex_confirmed_zero_must_not_overwrite_mid_cache()
    {
        Assert.False(ReadingProgressIndex.ShouldReplaceCachedIndex(7, 40, 0, 40, true));
        Assert.True(ReadingProgressIndex.ShouldReplaceCachedIndex(7, 40, 0, 40, true, true));
        Assert.True(ReadingProgressIndex.ShouldReplaceCachedIndex(7, 40, 0, 12, false));
    }

    [Fact]
    public void ReadingProgressIndex_percent_and_status_label()
    {
        Assert.Equal(0.40, ReadingProgressIndex.Percent(4, 10), 4);
        Assert.Equal(1.0, ReadingProgressIndex.Percent(9, 10), 4);
        Assert.True(ReadingProgressIndex.IsFinished(9, 10));
        Assert.Equal("已读完", ReadingProgressIndex.StatusLabel(true, 9, 10));
        Assert.Equal(0.40, ReadingProgressIndex.Percent(4, 80, 0, 10), 4);
        Assert.Equal("未读", ReadingProgressIndex.StatusLabel(false, 4, 10));
        Assert.Equal("在读 · 1/10 段", ReadingProgressIndex.StatusLabel(true, 0, 10));
        Assert.Equal("在读 · 5/10 段", ReadingProgressIndex.StatusLabel(true, 4, 10));
        Assert.Equal(0, ReadingProgressIndex.Percent(0, 1), 4);
        Assert.False(ReadingProgressIndex.IsFinished(0, 1));
        Assert.Equal("在读 · 1/1 段", ReadingProgressIndex.StatusLabel(true, 0, 1));
    }

    [Fact]
    public void ReadingProgressIndex_overlay_local_applies_percent_until_resegment()
    {
        var book = new BookSummary
        {
            SegmentCount = 10,
            LastOpenedAt = "2024-05-01T00:00:00Z",
            CurrentSegmentIndex = 1,
        };
        ReadingProgressIndex.OverlayLocal(book, 4, 10, 0.45);
        Assert.Equal(4, book.CurrentSegmentIndex);
        Assert.Equal(0.45, book.ReadingPercent);
        Assert.Equal("在读 · 5/10 段", book.ReadingStatusLabel);

        var resegmented = new BookSummary
        {
            SegmentCount = 4,
            LastOpenedAt = "2024-05-01T00:00:00Z",
            CurrentSegmentIndex = 0,
        };
        ReadingProgressIndex.OverlayLocal(resegmented, 9, 12, 0.9);
        Assert.Equal(0, resegmented.CurrentSegmentIndex);
        Assert.Null(resegmented.ReadingPercent);
        Assert.Equal("在读 · 1/4 段", resegmented.ReadingStatusLabel);
    }

    [Fact]
    public void SegmentTurnNavigation_middle_first_last_and_empty()
    {
        int[] sorted = [0, 2, 5];
        Assert.Equal(0, SegmentTurnNavigation.TargetIdx(sorted, 2, -1));
        Assert.Equal(5, SegmentTurnNavigation.TargetIdx(sorted, 2, 1));
        Assert.Null(SegmentTurnNavigation.TargetIdx(sorted, 0, -1));
        Assert.Null(SegmentTurnNavigation.TargetIdx(sorted, 5, 1));
        Assert.Null(SegmentTurnNavigation.TargetIdx([], 0, 1));
        Assert.Null(SegmentTurnNavigation.TargetIdx(sorted, 9, 1));
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
            if (path == "/books/b1/resegment/cancel")
            {
                Assert.Equal(HttpMethod.Post, req.Method);
                return Json("{}");
            }
            if (path == "/books/b1/ingest/cancel")
            {
                Assert.Equal(HttpMethod.Post, req.Method);
                return Json("{}");
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
        await client.CancelResegmentBookAsync("b1");
        await client.CancelIngestAsync("b1");
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
