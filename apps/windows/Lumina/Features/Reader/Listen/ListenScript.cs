using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace Lumina.Features.Reader.Listen;

public enum ListenMode
{
    Summary,
    Detailed,
    Original,
}

public abstract record ListenHighlightAnchor
{
    public sealed record SegmentTitle : ListenHighlightAnchor;
    public sealed record SummarySentence(int Index) : ListenHighlightAnchor;
    public sealed record SectionBullets : ListenHighlightAnchor;
    public sealed record Bullet(int Index) : ListenHighlightAnchor;
    public sealed record OriginalUtf16(int Start, int Length) : ListenHighlightAnchor;
}

public sealed record ListenUtterance(string Text, ListenHighlightAnchor Anchor);

/// Policy for listen follow-along UI side effects.
public static class ListenFollowHighlightPolicy
{
    /// Must stay false: auto-scrolling spoken lines fights continuous play advance.
    public const bool ScrollsUtteranceIntoView = false;
}

public sealed record ListenScript(
    ListenMode Mode,
    string Language,
    IReadOnlyList<ListenUtterance> Utterances,
    bool Ready,
    string? SkipReason)
{
    public const string SectionBullets = "主要内容";
    public const string SectionNotes = "需要注意";
    public const int MaxUtteranceChars = 800;

    public IReadOnlyList<string> Texts => Utterances.Select(u => u.Text).ToList();

    public static ListenScript NotReady(ListenMode mode, string reason, string language = "zh") =>
        new(mode, language, [], false, reason);
}

/// Whether / how to announce chapter before segment label (PRD §5.3.1).
public abstract record ListenChapterSpeakContext
{
    public sealed record SessionStart : ListenChapterSpeakContext;
    public sealed record Continuing(string? PreviousSpokenChapter) : ListenChapterSpeakContext;
}

public static class ListenChapterAnnouncePolicy
{
    public static string? NormalizedChapter(string? raw)
    {
        var cleaned = SegmentCatalogPolicy.StripSectionMark(raw ?? "");
        return cleaned.Length == 0 ? null : cleaned;
    }

    public static bool ShouldAnnounce(string? chapter, ListenChapterSpeakContext context)
    {
        var current = NormalizedChapter(chapter);
        if (current is null) return false;
        return context switch
        {
            ListenChapterSpeakContext.SessionStart => true,
            ListenChapterSpeakContext.Continuing cont =>
                NormalizedChapter(cont.PreviousSpokenChapter) != current,
            _ => false,
        };
    }

    public static List<string> TitlePrefix(
        string? segmentLabel,
        string? chapter,
        ListenChapterSpeakContext context)
    {
        var lines = new List<string>();
        var chapterName = NormalizedChapter(chapter);
        var announce = ShouldAnnounce(chapter, context);
        if (announce && chapterName is not null)
            lines.Add(chapterName);
        var title = ListenScriptBuilder.SegmentTitle(segmentLabel);
        if (title is not null)
        {
            if (title != chapterName)
                lines.Add(title);
            else if (!announce)
                lines.Add(title);
        }
        return lines;
    }
}

public static class ListenScriptBuilder
{
    private static readonly Regex CjkRe = new(@"[\u4e00-\u9fff]", RegexOptions.Compiled);

    public static ListenMode ParseMode(string? raw)
    {
        return (raw ?? "").Trim().ToLowerInvariant() switch
        {
            "detailed" => ListenMode.Detailed,
            "original" => ListenMode.Original,
            _ => ListenMode.Summary,
        };
    }

    public static string Label(ListenMode mode) => mode switch
    {
        ListenMode.Detailed => "听完整摘要",
        ListenMode.Original => "听原文",
        _ => "听简要摘要",
    };

    public static string ShortLabel(ListenMode mode) => mode switch
    {
        ListenMode.Detailed => "完整摘要",
        ListenMode.Original => "原文",
        _ => "简要摘要",
    };

    public static bool IsSummaryLayer(ListenMode mode) =>
        mode is ListenMode.Summary or ListenMode.Detailed;

    public static string DetectLanguage(string text)
    {
        var trimmed = text.Trim();
        if (trimmed.Length == 0) return "zh";
        var cjk = CjkRe.Matches(trimmed).Count;
        var letters = trimmed.Count(ch => (ch is >= 'A' and <= 'Z') || (ch is >= 'a' and <= 'z'));
        return cjk >= Math.Max(1, letters) ? "zh" : "en";
    }

    public static ListenScript Build(
        ListenMode mode,
        string? summaryJson,
        string? rawText,
        string? languageHint = null,
        string? segmentLabel = null,
        string? chapter = null,
        ListenChapterSpeakContext? chapterContext = null)
    {
        chapterContext ??= new ListenChapterSpeakContext.SessionStart();
        var prefix = ListenChapterAnnouncePolicy.TitlePrefix(segmentLabel, chapter, chapterContext);
        if (mode == ListenMode.Original)
        {
            var source = rawText ?? "";
            var text = source.Trim();
            if (text.Length == 0)
                return ListenScript.NotReady(ListenMode.Original, "empty_text", languageHint ?? "zh");
            var utterances = new List<ListenUtterance>();
            foreach (var line in prefix)
                utterances.AddRange(AnchoredChunks(line, new ListenHighlightAnchor.SegmentTitle()));
            utterances.AddRange(OriginalUtterances(source));
            var language = languageHint ?? DetectLanguage(text);
            if (utterances.Count == 0)
                return ListenScript.NotReady(ListenMode.Original, "empty_text", language);
            return new ListenScript(ListenMode.Original, language, utterances, true, null);
        }

        if (!TryParseSummary(summaryJson, out var sentences, out var bullets, out var notes))
            return ListenScript.NotReady(mode, "summary_not_ready", languageHint ?? "zh");

        var utterancesSummary = new List<ListenUtterance>();
        foreach (var line in prefix)
            utterancesSummary.AddRange(AnchoredChunks(line, new ListenHighlightAnchor.SegmentTitle()));
        for (var i = 0; i < sentences.Count; i++)
        {
            var sentence = sentences[i].Trim();
            if (sentence.Length == 0) continue;
            utterancesSummary.AddRange(AnchoredChunks(sentence, new ListenHighlightAnchor.SummarySentence(i)));
        }
        if (mode == ListenMode.Detailed)
        {
            var kept = new List<(int SourceIndex, (string Label, string Body) Bullet)>();
            for (var i = 0; i < bullets.Count; i++)
            {
                if (bullets[i].Body.Trim().Length == 0) continue;
                kept.Add((i, bullets[i]));
            }
            if (kept.Count > 0)
            {
                utterancesSummary.AddRange(AnchoredChunks(
                    ListenScript.SectionBullets, new ListenHighlightAnchor.SectionBullets()));
                for (var display = 0; display < kept.Count; display++)
                {
                    var (sourceIndex, bullet) = kept[display];
                    var line = FormatBullet(display + 1, bullet.Label, bullet.Body);
                    utterancesSummary.AddRange(AnchoredChunks(
                        line, new ListenHighlightAnchor.Bullet(sourceIndex)));
                }
            }
        }

        var sampleParts = new List<string>();
        sampleParts.AddRange(prefix);
        sampleParts.AddRange(sentences);
        sampleParts.AddRange(bullets.Select(b => b.Body));
        sampleParts.AddRange(notes);
        var sample = string.Join(" ", sampleParts);
        var lang = languageHint ?? DetectLanguage(sample);
        if (utterancesSummary.Count == 0)
            return ListenScript.NotReady(mode, "summary_not_ready", lang);
        return new ListenScript(mode, lang, utterancesSummary, true, null);
    }

    /// Condensed segment title only; blank means skip (no 段 N fallback).
    public static string? SegmentTitle(string? segmentLabel)
    {
        var cleaned = (segmentLabel ?? "").Trim();
        return cleaned.Length == 0 ? null : cleaned;
    }

    public static string FormatBullet(int index, string? label, string body)
    {
        if (!string.IsNullOrEmpty(label))
            return $"{index}. {label}。{body}";
        return $"{index}. {body}";
    }

    public static List<string> SplitSentences(string text)
    {
        var raw = text.Trim();
        if (raw.Length == 0) return [];
        var result = new List<string>();
        var current = new StringBuilder();
        var chars = raw.ToCharArray();
        var i = 0;
        var cnStops = new HashSet<char> { '。', '！', '？', '；' };
        while (i < chars.Length)
        {
            var ch = chars[i];
            if (ch == '\n')
            {
                var piece = current.ToString().Trim();
                if (piece.Length > 0) result.Add(piece);
                current.Clear();
                i += 1;
                continue;
            }
            current.Append(ch);
            var isCn = cnStops.Contains(ch);
            var isBang = ch is '!' or '?';
            var isPeriod = ch == '.' && (i + 1 >= chars.Length || !char.IsDigit(chars[i + 1]));
            if (isCn || isBang || isPeriod)
            {
                var j = i + 1;
                while (j < chars.Length && char.IsWhiteSpace(chars[j])) j += 1;
                var piece = current.ToString().Trim();
                if (piece.Length > 0) result.Add(piece);
                current.Clear();
                i = j;
                continue;
            }
            i += 1;
        }
        var tail = current.ToString().Trim();
        if (tail.Length > 0) result.Add(tail);
        return result.Count == 0 ? [raw] : result;
    }

    public static List<string> ChunkLong(string text, int maxChars = ListenScript.MaxUtteranceChars)
    {
        var cleaned = Regex.Replace(text.Trim(), @"\s+", " ");
        if (cleaned.Length == 0) return [];
        if (cleaned.Length <= maxChars) return [cleaned];
        var chunks = new List<string>();
        var remaining = cleaned;
        while (remaining.Length > 0)
        {
            if (remaining.Length <= maxChars)
            {
                chunks.Add(remaining);
                break;
            }
            var window = remaining[..maxChars];
            var cut = LastBreak(window) ?? maxChars;
            cut = Math.Min(cut, remaining.Length);
            var piece = remaining[..cut].Trim();
            if (piece.Length > 0) chunks.Add(piece);
            remaining = remaining[cut..].Trim();
        }
        return chunks;
    }

    private static List<ListenUtterance> AnchoredChunks(string text, ListenHighlightAnchor anchor)
    {
        return ChunkLong(text).Select(chunk => new ListenUtterance(chunk, anchor)).ToList();
    }

    private static List<ListenUtterance> OriginalUtterances(string source)
    {
        var outList = new List<ListenUtterance>();
        var searchFrom = 0;
        foreach (var piece in SplitSentences(source))
        {
            var located = LocateRange(piece, source, ref searchFrom);
            var chunks = ChunkLong(piece);
            if (located is null)
            {
                outList.AddRange(AnchoredChunks(piece, new ListenHighlightAnchor.OriginalUtf16(0, 0)));
                continue;
            }
            var (start, length) = located.Value;
            foreach (var chunk in chunks)
                outList.Add(new ListenUtterance(chunk, new ListenHighlightAnchor.OriginalUtf16(start, length)));
        }
        return outList;
    }

    private static (int Start, int Length)? LocateRange(string needle, string haystack, ref int searchFrom)
    {
        if (searchFrom < 0) searchFrom = 0;
        if (searchFrom > haystack.Length) searchFrom = 0;
        var idx = haystack.IndexOf(needle, searchFrom, StringComparison.Ordinal);
        if (idx < 0)
            idx = haystack.IndexOf(needle, StringComparison.Ordinal);
        if (idx < 0) return null;
        searchFrom = idx + needle.Length;
        return (idx, needle.Length);
    }

    private static int? LastBreak(string window)
    {
        string[] marks = ["。", "！", "？", "；", "，", ". ", " "];
        int? best = null;
        foreach (var mark in marks)
        {
            var idx = window.LastIndexOf(mark, StringComparison.Ordinal);
            if (idx < 0) continue;
            var end = idx + mark.Length;
            if (end >= window.Length / 3)
                best = Math.Max(best ?? 0, end);
        }
        return best;
    }

    private static bool TryParseSummary(
        string? summaryJson,
        out List<string> sentences,
        out List<(string Label, string Body)> bullets,
        out List<string> notes)
    {
        sentences = [];
        bullets = [];
        notes = [];
        if (string.IsNullOrWhiteSpace(summaryJson)) return false;
        try
        {
            using var doc = JsonDocument.Parse(summaryJson);
            if (doc.RootElement.ValueKind != JsonValueKind.Object) return false;
            var root = doc.RootElement;
            sentences = StringList(root, "sentences");
            bullets = BulletList(root, "bullets");
            notes = StringList(root, "notes");
            return sentences.Count > 0 || bullets.Count > 0 || notes.Count > 0;
        }
        catch (JsonException)
        {
            return false;
        }
    }

    private static List<string> StringList(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var el) || el.ValueKind != JsonValueKind.Array)
            return [];
        var outList = new List<string>();
        foreach (var item in el.EnumerateArray())
        {
            if (item.ValueKind == JsonValueKind.String)
            {
                var value = SummaryJsonParser.CollapseProseWhitespace(item.GetString());
                if (value.Length > 0) outList.Add(value);
            }
        }
        return outList;
    }

    private static List<(string Label, string Body)> BulletList(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var el) || el.ValueKind != JsonValueKind.Array)
            return [];
        var outList = new List<(string, string)>();
        foreach (var item in el.EnumerateArray())
        {
            if (item.ValueKind == JsonValueKind.Object)
            {
                var label = Prop(item, "label");
                var body = Prop(item, "body");
                if (body.Length == 0) body = Prop(item, "content");
                if (body.Length == 0) body = Prop(item, "text");
                if (body.Length == 0 && label.Length > 0)
                {
                    body = label;
                    label = "";
                }
                if (body.Length > 0) outList.Add((label, body));
            }
            else if (item.ValueKind == JsonValueKind.String)
            {
                var value = SummaryJsonParser.CollapseProseWhitespace(item.GetString());
                if (value.Length > 0) outList.Add(("", value));
            }
        }
        return outList;
    }

    private static string Prop(JsonElement obj, string name)
    {
        if (!obj.TryGetProperty(name, out var el)) return "";
        return el.ValueKind == JsonValueKind.String
            ? SummaryJsonParser.CollapseProseWhitespace(el.GetString())
            : "";
    }
}

/// Speaker click follows the panel on screen. Windows uses a global 原文 toggle;
/// macOS also has per-segment 切换原文 / 切换摘要, encoded as the expanded flags.
public static class ListenChromePolicy
{
    public static bool IsShowingOriginal(bool originalLayer, bool sourceExpanded, bool summaryExpanded)
    {
        if (originalLayer) return !summaryExpanded;
        return sourceExpanded;
    }

    public static ListenMode PrimaryMode(bool showingOriginal) =>
        showingOriginal ? ListenMode.Original : ListenMode.Summary;

    public static bool ShowsSummaryChevron(bool showingOriginal) => !showingOriginal;
}
