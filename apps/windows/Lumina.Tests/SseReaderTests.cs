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
}
