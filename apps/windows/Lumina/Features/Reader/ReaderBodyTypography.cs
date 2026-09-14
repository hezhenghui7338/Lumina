namespace Lumina.Features.Reader;

/// <summary>
/// Reader original-body typography. Collapse whitespace-only lines so EPUB/HTML
/// wrapper noise does not paint as blank rows (matches pre-v0.5 macOS
/// LazyParagraphText empty-chunk skip). Keep raw text when a search highlight
/// range is active so UTF-16 offsets stay valid.
/// </summary>
public static class ReaderBodyTypography
{
    public static string DisplayText(string raw, bool preservingHighlight)
    {
        if (preservingHighlight) return raw;
        return CollapseEmptyLines(raw);
    }

    public static string CollapseEmptyLines(string raw)
    {
        if (string.IsNullOrEmpty(raw)) return raw;
        var unified = raw.Replace("\r\n", "\n").Replace('\r', '\n');
        var parts = unified.Split('\n');
        var kept = new List<string>(parts.Length);
        foreach (var line in parts)
        {
            if (string.IsNullOrWhiteSpace(line)) continue;
            kept.Add(line);
        }
        return string.Join("\n", kept);
    }
}
