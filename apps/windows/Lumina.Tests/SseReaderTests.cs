using System.Text;
using Lumina.Services;
using Xunit;

namespace Lumina.Tests;

public class SseReaderTests
{
    [Fact]
    public async Task ReadDataEventsAsync_parses_data_lines()
    {
        var payload = "event: ping\n\ndata: {\"type\":\"token\",\"content\":\"hi\"}\n\ndata: {\"type\":\"done\"}\n\n";
        await using var stream = new MemoryStream(Encoding.UTF8.GetBytes(payload));
        var events = new List<string>();
        await foreach (var el in SseReader.ReadDataEventsAsync(stream))
        {
            events.Add(el.GetProperty("type").GetString()!);
        }
        Assert.Equal(new[] { "token", "done" }, events);
    }

    [Fact]
    public void BookSummary_progress_label()
    {
        var book = new BookSummary
        {
            Title = "t",
            Status = "reading",
            SegmentCount = 10,
            SummaryReadyCount = 3,
            SummaryTotalCount = 10,
        };
        Assert.Equal("在读 · 摘要 3/10", book.ProgressLabel);
    }

    [Fact]
    public void BookSummary_error_status_includes_ingest_error()
    {
        var bare = new BookSummary { Title = "金阁寺", Status = "error" };
        Assert.Equal("导入失败", bare.StatusLabel);
        Assert.Equal("导入失败", bare.CardStatusLine);

        var withReason = new BookSummary
        {
            Title = "金阁寺",
            Status = "error",
            IngestError = "unknown encoding: utf-8-sig",
        };
        Assert.Equal("导入失败：unknown encoding: utf-8-sig", withReason.StatusLabel);
        Assert.Equal("导入失败：unknown encoding: utf-8-sig", withReason.CardStatusLine);
    }

    [Fact]
    public void BookSummary_completed_summary_uses_reading_status()
    {
        var unread = new BookSummary
        {
            Title = "t",
            Status = "summarized",
            SegmentCount = 10,
            SummaryReadyCount = 10,
            SummaryTotalCount = 10,
        };
        Assert.Equal("未读", unread.ProgressLabel);

        var reading = new BookSummary
        {
            Title = "t",
            Status = "summarized",
            SegmentCount = 10,
            SummaryReadyCount = 10,
            SummaryTotalCount = 10,
            LastOpenedAt = "2026-08-22T12:00:00Z",
            CurrentSegmentIndex = 4,
        };
        Assert.Equal("在读 · 5/10 段", reading.ProgressLabel);

        var lastSegmentTop = new BookSummary
        {
            Title = "t",
            Status = "summarized",
            SegmentCount = 10,
            SummaryReadyCount = 10,
            SummaryTotalCount = 10,
            LastOpenedAt = "2026-08-22T12:00:00Z",
            CurrentSegmentIndex = 9,
        };
        Assert.Equal("已读完", lastSegmentTop.ProgressLabel);

        var finished = new BookSummary
        {
            Title = "t",
            Status = "summarized",
            SegmentCount = 10,
            SummaryReadyCount = 10,
            SummaryTotalCount = 10,
            LastOpenedAt = "2026-08-22T12:00:00Z",
            CurrentSegmentIndex = 9,
            ReadingPercent = 1.0,
        };
        Assert.Equal("已读完", finished.ProgressLabel);
    }

    [Fact]
    public void BookSummary_can_chat_book_requires_ready_index()
    {
        var notReady = new BookSummary
        {
            Status = "summarized",
            SegmentCount = 3,
            SummaryReadyCount = 3,
            SummaryTotalCount = 3,
            IndexStatus = "building",
        };
        Assert.False(notReady.CanChatBook);
        Assert.Equal("全书（索引生成中）", notReady.BookChatLabel);

        var ready = new BookSummary
        {
            Status = "summarized",
            SegmentCount = 3,
            SummaryReadyCount = 3,
            SummaryTotalCount = 3,
            IndexStatus = "ready",
        };
        Assert.True(ready.CanChatBook);
        Assert.Equal("全书", ready.BookChatLabel);
    }

    [Fact]
    public void BookSummary_can_resegment_requires_ready_book()
    {
        var ready = new BookSummary { Status = "reading", SegmentCount = 7 };
        Assert.True(ready.CanResegment);

        var processing = new BookSummary
        {
            Status = "processing",
            SegmentCount = 7,
            ProcessingKind = "resegment",
        };
        Assert.False(processing.CanResegment);

        var failed = new BookSummary { Status = "error", SegmentCount = 0 };
        Assert.False(failed.CanResegment);
        Assert.False(failed.CanOpenInReader);

        var unsegmented = new BookSummary { Status = "unread", SegmentCount = 0 };
        Assert.False(unsegmented.CanResegment);
        Assert.True(unsegmented.IsSegmenting);
        Assert.True(unsegmented.CanOpenInReader);

        var processingOpen = new BookSummary
        {
            Status = "processing",
            SegmentCount = 0,
            SummarizeState = "segmenting",
        };
        Assert.True(processingOpen.IsSegmenting);
        Assert.True(processingOpen.CanOpenInReader);

        var readyOpen = new BookSummary { Status = "reading", SegmentCount = 4 };
        Assert.True(readyOpen.CanOpenInReader);
    }

    [Fact]
    public void ResegmentTarget_normalizes_and_clamps()
    {
        Assert.Equal(200, ResegmentTarget.Normalized(50, null, 0));
        Assert.Equal(200, ResegmentTarget.Normalized(200, null, 0));
        Assert.Equal(8000, ResegmentTarget.Normalized(9000, null, 0));
        Assert.Equal(3449, ResegmentTarget.Normalized(3449, null, 0));
        Assert.Equal(3366, ResegmentTarget.Normalized(null, 10100, 3));
    }

    [Fact]
    public void ResegmentTarget_presets_and_provider_defaults()
    {
        Assert.Equal(new[] { 500, 1000, 1500, 2000, 2500 }, ResegmentTarget.Presets);
        Assert.Equal(2500, ResegmentTarget.DefaultFor("ollama"));
        Assert.Equal(3500, ResegmentTarget.DefaultFor("openrouter"));
        Assert.Equal(4000, ResegmentTarget.DefaultFor("openai"));
        Assert.Equal(4000, ResegmentTarget.MaxFor("ollama"));
        Assert.Equal(8000, ResegmentTarget.MaxFor("openai"));
        Assert.Equal(2500, ResegmentTarget.Effective(0, "ollama"));
        Assert.Equal(1500, ResegmentTarget.Effective(1500, "ollama"));
        Assert.Equal(0, ResegmentTarget.ToStored(2500, "ollama"));
        Assert.Equal(1500, ResegmentTarget.ToStored(1500, "ollama"));
        Assert.Equal(4000, ResegmentTarget.ToStored(9000, "ollama"));
    }
}
