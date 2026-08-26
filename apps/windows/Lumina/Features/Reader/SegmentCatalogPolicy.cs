using Lumina.Services;

namespace Lumina.Features.Reader;

public sealed class SegmentCatalogItem
{
    public bool IsHeader { get; init; }
    public string ChapterKey { get; init; } = "";
    public string HeaderText { get; init; } = "";
    public bool IsCollapsed { get; init; }
    public int HeaderCount { get; init; }
    public SegmentRow? Segment { get; init; }

    public string Headline => Segment?.CatalogHeadline ?? HeaderText;
    public string Preview => Segment?.SummaryPreview ?? "";
    public string Bullets => Segment?.BulletLabelsLine ?? "";
    public double TitleSize => IsHeader ? 13 : 16;
    public double TitleOpacity => IsHeader ? 0.82 : 1;
    public double RowSpacing => IsHeader ? 0 : 6;
    public double PreviewSize => string.IsNullOrEmpty(Preview) ? 0 : 15;
    public double BulletSize => string.IsNullOrEmpty(Bullets) ? 0 : 14;
}

public static class SegmentCatalogPolicy
{
    public const string UngroupedKey = "";

    public static string ChapterKey(SegmentRow row)
    {
        var ch = row.Chapter?.Trim();
        return string.IsNullOrEmpty(ch) ? UngroupedKey : ch;
    }

    public static bool ShouldGroup(IReadOnlyList<SegmentRow> segments) =>
        segments.Any(s => !string.IsNullOrWhiteSpace(s.Chapter));

    public static string HeaderTitle(string chapterKey) =>
        string.IsNullOrEmpty(chapterKey) ? "未分章" : $"§ {chapterKey}";

    public static IReadOnlyList<SegmentCatalogItem> Build(
        IReadOnlyList<SegmentRow> segments,
        IReadOnlySet<string> collapsed)
    {
        if (segments.Count == 0) return [];
        if (!ShouldGroup(segments))
        {
            return segments.Select(s => new SegmentCatalogItem { Segment = s }).ToList();
        }

        var items = new List<SegmentCatalogItem>();
        string? current = null;
        var bucket = new List<SegmentRow>();

        void Flush()
        {
            if (current is null) return;
            var key = current;
            var collapsedNow = collapsed.Contains(key);
            var title = HeaderTitle(key);
            var glyph = collapsedNow ? "▸" : "▾";
            items.Add(new SegmentCatalogItem
            {
                IsHeader = true,
                ChapterKey = key,
                HeaderText = $"{glyph} {title}  {bucket.Count}",
                IsCollapsed = collapsedNow,
                HeaderCount = bucket.Count,
            });
            if (!collapsedNow)
            {
                foreach (var s in bucket)
                    items.Add(new SegmentCatalogItem { Segment = s, ChapterKey = key });
            }
            bucket.Clear();
        }

        foreach (var s in segments)
        {
            var key = ChapterKey(s);
            if (current is null)
                current = key;
            else if (key != current)
            {
                Flush();
                current = key;
            }
            bucket.Add(s);
        }
        Flush();
        return items;
    }
}
