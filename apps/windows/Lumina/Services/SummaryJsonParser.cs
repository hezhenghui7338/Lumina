using System.Text.Json;
using System.Text.RegularExpressions;

namespace Lumina.Services;

public static class SummaryJsonParser
{
    private static readonly Regex CjkNewline = new(
        @"(?<=[\u3400-\u9fff\u3000-\u303f\uff00-\uffef])[ \t]*\n+[ \t]*(?=[\u3400-\u9fff\u3000-\u303f\uff00-\uffef])",
        RegexOptions.Compiled);
    private static readonly Regex NewlineRun = new(@"[ \t]*\n+[ \t]*", RegexOptions.Compiled);
    private static readonly Regex HorizontalWs = new(@"[ \t]+", RegexOptions.Compiled);

    public static StructuredSummary Parse(string? summaryJson)
    {
        var result = new StructuredSummary();
        if (string.IsNullOrWhiteSpace(summaryJson))
            return result;

        try
        {
            using var doc = JsonDocument.Parse(summaryJson);
            var root = doc.RootElement;
            result.ThreeSentence =
                CollapseProse(GetString(root, "three_sentence"))
                ?? CollapseProse(GetString(root, "threeSentence"))
                ?? CollapseProse(GetString(root, "summary"))
                ?? CollapseProse(GetString(root, "overview"));
            result.KeyPoints = GetStringList(root, "key_points")
                ?? GetStringList(root, "keyPoints")
                ?? GetStringList(root, "points")
                ?? [];
            result.WatchOuts = GetStringList(root, "watch_outs")
                ?? GetStringList(root, "watchOuts")
                ?? GetStringList(root, "需要注意")
                ?? GetStringList(root, "caveats")
                ?? GetStringList(root, "notes")
                ?? [];
            result.FollowUps = GetStringList(root, "follow_ups")
                ?? GetStringList(root, "followUps")
                ?? GetStringList(root, "followup")
                ?? GetStringList(root, "questions")
                ?? [];

            if (string.IsNullOrWhiteSpace(result.ThreeSentence))
            {
                var sentences = GetStringList(root, "sentences");
                if (sentences is { Count: > 0 })
                    result.ThreeSentence = string.Join("\n", sentences);
            }

            if (result.KeyPoints.Count == 0)
            {
                var bullets = GetBulletLines(root, "bullets");
                if (bullets.Count > 0)
                    result.KeyPoints = bullets;
            }

            if (string.IsNullOrWhiteSpace(result.ThreeSentence) &&
                result.KeyPoints.Count == 0 &&
                result.WatchOuts.Count == 0)
            {
                result.RawFallback = summaryJson.Trim();
            }
        }
        catch (JsonException)
        {
            result.RawFallback = summaryJson.Trim();
        }
        return result;
    }

    /// <summary>Summary prose is single-line in the reader; collapse blank lines.</summary>
    public static string CollapseProseWhitespace(string? text)
    {
        if (string.IsNullOrWhiteSpace(text)) return "";
        var value = text.Trim();
        value = CjkNewline.Replace(value, "");
        value = NewlineRun.Replace(value, " ");
        value = HorizontalWs.Replace(value, " ");
        return value.Trim();
    }

    private static string? CollapseProse(string? text)
    {
        var cleaned = CollapseProseWhitespace(text);
        return cleaned.Length == 0 ? null : cleaned;
    }

    private static string? GetString(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var el)) return null;
        return el.ValueKind == JsonValueKind.String ? el.GetString() : el.ToString();
    }

    private static List<string>? GetStringList(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var el) || el.ValueKind != JsonValueKind.Array)
            return null;
        var list = new List<string>();
        foreach (var item in el.EnumerateArray())
        {
            var s = item.ValueKind == JsonValueKind.String ? item.GetString() : item.ToString();
            var cleaned = CollapseProseWhitespace(s);
            if (cleaned.Length > 0) list.Add(cleaned);
        }
        return list;
    }

    private static List<string> GetBulletLines(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var el) || el.ValueKind != JsonValueKind.Array)
            return [];
        var list = new List<string>();
        foreach (var item in el.EnumerateArray())
        {
            if (item.ValueKind == JsonValueKind.Object)
            {
                var label = CollapseProseWhitespace(Prop(item, "label"));
                var body = CollapseProseWhitespace(Prop(item, "body"));
                if (body.Length == 0) body = CollapseProseWhitespace(Prop(item, "content"));
                if (body.Length == 0) body = CollapseProseWhitespace(Prop(item, "text"));
                if (body.Length == 0 && label.Length > 0)
                {
                    list.Add(label);
                    continue;
                }
                if (body.Length == 0) continue;
                list.Add(label.Length > 0 ? $"{label}：{body}" : body);
            }
            else if (item.ValueKind == JsonValueKind.String)
            {
                var cleaned = CollapseProseWhitespace(item.GetString());
                if (cleaned.Length > 0) list.Add(cleaned);
            }
        }
        return list;
    }

    private static string Prop(JsonElement obj, string name)
    {
        if (!obj.TryGetProperty(name, out var el) || el.ValueKind != JsonValueKind.String)
            return "";
        return el.GetString() ?? "";
    }
}
