using Lumina.Services;

namespace Lumina.Features.Reader;

public sealed class SegmentCatalogItem
{
    public bool IsHeader { get; init; }
    public string ChapterKey { get; init; } = "";
    public string HeaderText { get; init; } = "";
    public bool IsCollapsed { get; init; }
    public int HeaderCount { get; init; }
    public int Depth { get; init; }
    public bool Grouped { get; init; }
    public SegmentRow? Segment { get; init; }

    public string Headline =>
        Segment is null
            ? HeaderText
            : Grouped
                ? Segment.CatalogHeadlineGrouped
                : Segment.CatalogHeadline;

    public string Preview => Segment?.SummaryPreview ?? "";
    public string Bullets => Segment?.BulletLabelsLine ?? "";
    public double TitleSize => IsHeader ? 13 : 16;
    public double TitleOpacity => IsHeader ? 0.82 : 1;
    public double RowSpacing => IsHeader ? 0 : 6;
    public double PreviewSize => string.IsNullOrEmpty(Preview) ? 0 : 15;
    public double BulletSize => string.IsNullOrEmpty(Bullets) ? 0 : 14;
    public double IndentLeft => Depth * 12;
}

public static class SegmentCatalogPolicy
{
    public const string UngroupedKey = "";
    public const string UngroupedTitle = "未分章";
    public const string KeySeparator = "/";

    public static string StripSectionMark(string? raw)
    {
        var name = (raw ?? "").Trim();
        while (name.Length > 0 && name[0] == '§')
            name = name[1..].Trim();
        while (name.Length > 0 && name[^1] == '§')
            name = name[..^1].Trim();
        return name;
    }

    public static IReadOnlyList<string> FromChapter(string? chapter)
    {
        var name = StripSectionMark(chapter);
        if (string.IsNullOrEmpty(name)) return [];
        var parts = new List<string>();
        foreach (var piece in name.Split('·', StringSplitOptions.RemoveEmptyEntries))
        {
            var cleaned = StripSectionMark(piece);
            if (!string.IsNullOrEmpty(cleaned)) parts.Add(cleaned);
            if (parts.Count >= 2) break;
        }
        return parts;
    }

    public static IReadOnlyList<string> ResolvePath(SegmentRow row)
    {
        if (row.HeadingPath is { Count: > 0 })
        {
            var stored = new List<string>();
            foreach (var item in row.HeadingPath)
            {
                var cleaned = StripSectionMark(item);
                if (!string.IsNullOrEmpty(cleaned)) stored.Add(cleaned);
                if (stored.Count >= 2) break;
            }
            if (stored.Count > 0) return stored;
        }
        return FromChapter(row.Chapter);
    }

    public static string PathKey(IReadOnlyList<string> parts) =>
        string.Join(KeySeparator, parts);

    public static IReadOnlyList<string> AncestorKeys(IReadOnlyList<string> parts)
    {
        var keys = new List<string>();
        var acc = new List<string>();
        foreach (var part in parts)
        {
            acc.Add(part);
            keys.Add(PathKey(acc));
        }
        return keys;
    }

    public static IReadOnlyList<string> AncestorKeys(SegmentRow row)
    {
        var resolved = ResolvePath(row);
        var parts = resolved.Count == 0 ? new[] { UngroupedKey } : resolved.ToArray();
        return AncestorKeys(parts);
    }

    public static string ChapterKey(SegmentRow row)
    {
        var path = ResolvePath(row);
        return path.Count == 0 ? UngroupedKey : PathKey(path);
    }

    public static bool ShouldGroup(IReadOnlyList<SegmentRow> segments) =>
        segments.Any(s => ResolvePath(s).Count > 0);

    public static string HeaderTitle(string chapterKey)
    {
        if (string.IsNullOrWhiteSpace(chapterKey) || chapterKey == UngroupedKey)
            return UngroupedTitle;
        var leaf = chapterKey.Split(KeySeparator).LastOrDefault() ?? chapterKey;
        var name = StripSectionMark(leaf);
        return string.IsNullOrEmpty(name) ? UngroupedTitle : name;
    }

    public static IReadOnlyList<SegmentCatalogItem> Build(
        IReadOnlyList<SegmentRow> segments,
        IReadOnlySet<string> collapsed)
    {
        if (segments.Count == 0) return [];
        if (!ShouldGroup(segments))
        {
            return segments.Select(s => new SegmentCatalogItem { Segment = s }).ToList();
        }

        var displayed = segments.Select(s =>
        {
            var resolved = ResolvePath(s);
            if (resolved.Count == 0)
                return (parts: (IReadOnlyList<string>)[UngroupedKey], titles: (IReadOnlyList<string>)[UngroupedTitle]);
            return (parts: resolved, titles: resolved);
        }).ToList();

        var counts = new Dictionary<string, int>(StringComparer.Ordinal);
        foreach (var item in displayed)
        {
            var acc = new List<string>();
            foreach (var part in item.parts)
            {
                acc.Add(part);
                var key = PathKey(acc);
                counts[key] = counts.GetValueOrDefault(key) + 1;
            }
        }

        bool PrefixCollapsed(IReadOnlyList<string> parts)
        {
            var acc = new List<string>();
            foreach (var part in parts)
            {
                acc.Add(part);
                if (collapsed.Contains(PathKey(acc))) return true;
            }
            return false;
        }

        var items = new List<SegmentCatalogItem>();
        var openPath = new List<string>();
        for (var i = 0; i < segments.Count; i++)
        {
            var segment = segments[i];
            var path = displayed[i].parts;
            var titles = displayed[i].titles;
            var common = 0;
            while (common < Math.Min(openPath.Count, path.Count) && openPath[common] == path[common])
                common++;
            if (common < openPath.Count)
                openPath.RemoveRange(common, openPath.Count - common);

            var skipChildren = common > 0 && PrefixCollapsed(path.Take(common).ToList());
            if (!skipChildren)
            {
                for (var index = common; index < path.Count; index++)
                {
                    var prefix = path.Take(index + 1).ToList();
                    if (index > 0 && PrefixCollapsed(prefix.Take(index).ToList()))
                    {
                        skipChildren = true;
                        break;
                    }
                    var key = PathKey(prefix);
                    var collapsedNow = collapsed.Contains(key);
                    var glyph = collapsedNow ? "▸" : "▾";
                    var count = counts.GetValueOrDefault(key);
                    items.Add(new SegmentCatalogItem
                    {
                        IsHeader = true,
                        ChapterKey = key,
                        HeaderText = $"{glyph} {titles[index]}  {count}",
                        IsCollapsed = collapsedNow,
                        HeaderCount = count,
                        Depth = index,
                        Grouped = true,
                    });
                    openPath.Add(path[index]);
                    if (collapsedNow)
                    {
                        skipChildren = true;
                        break;
                    }
                }
            }
            if (!skipChildren)
            {
                items.Add(new SegmentCatalogItem
                {
                    Segment = segment,
                    ChapterKey = PathKey(path),
                    Depth = path.Count,
                    Grouped = true,
                });
            }
        }
        return items;
    }
}
