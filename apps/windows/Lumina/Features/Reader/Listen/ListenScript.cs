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

public sealed record ListenUtterance(string Text);

public sealed record ListenScript(
    ListenMode Mode,
    string Language,
    IReadOnlyList<ListenUtterance> Utterances,
    bool Ready,
    string? SkipReason)
{
    public const string SectionBullets = "结构化要点";
    public const string SectionNotes = "需要注意";
    public const int MaxUtteranceChars = 800;

    public IReadOnlyList<string> Texts => Utterances.Select(u => u.Text).ToList();

    public static ListenScript NotReady(ListenMode mode, string reason, string language = "zh") =>
        new(mode, language, [], false, reason);
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
        string? languageHint = null)
    {
        if (mode == ListenMode.Original)
        {
            var text = (rawText ?? "").Trim();
            if (text.Length == 0)
                return ListenScript.NotReady(ListenMode.Original, "empty_text", languageHint ?? "zh");
            var utterances = UtterancesFrom(SplitSentences(text));
            var language = languageHint ?? DetectLanguage(text);
            if (utterances.Count == 0)
                return ListenScript.NotReady(ListenMode.Original, "empty_text", language);
            return new ListenScript(ListenMode.Original, language, utterances, true, null);
        }

        if (!TryParseSummary(summaryJson, out var sentences, out var bullets, out var notes))
            return ListenScript.NotReady(mode, "summary_not_ready", languageHint ?? "zh");

        var lines = new List<string>(sentences);
        if (mode == ListenMode.Detailed)
        {
            if (bullets.Count > 0)
            {
                lines.Add(ListenScript.SectionBullets);
                for (var i = 0; i < bullets.Count; i++)
                    lines.Add(FormatBullet(i + 1, bullets[i].Label, bullets[i].Body));
            }
        }

        var sample = string.Join(" ", sentences.Concat(bullets.Select(b => b.Body)).Concat(notes));
        var lang = languageHint ?? DetectLanguage(sample);
        var built = UtterancesFrom(lines);
        if (built.Count == 0)
            return ListenScript.NotReady(mode, "summary_not_ready", lang);
        return new ListenScript(mode, lang, built, true, null);
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

    private static List<ListenUtterance> UtterancesFrom(IEnumerable<string> lines)
    {
        var outList = new List<ListenUtterance>();
        foreach (var line in lines)
        {
            foreach (var chunk in ChunkLong(line))
                outList.Add(new ListenUtterance(chunk));
        }
        return outList;
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
                var value = item.GetString()?.Trim();
                if (!string.IsNullOrEmpty(value)) outList.Add(value);
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
                var value = item.GetString()?.Trim();
                if (!string.IsNullOrEmpty(value)) outList.Add(("", value));
            }
        }
        return outList;
    }

    private static string Prop(JsonElement obj, string name)
    {
        if (!obj.TryGetProperty(name, out var el)) return "";
        return el.ValueKind == JsonValueKind.String ? (el.GetString() ?? "").Trim() : "";
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
