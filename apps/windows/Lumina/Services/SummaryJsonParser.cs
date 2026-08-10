using System.Text.Json;

namespace Lumina.Services;

public static class SummaryJsonParser
{
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
                GetString(root, "three_sentence")
                ?? GetString(root, "threeSentence")
                ?? GetString(root, "summary")
                ?? GetString(root, "overview");
            result.KeyPoints = GetStringList(root, "key_points")
                ?? GetStringList(root, "keyPoints")
                ?? GetStringList(root, "points")
                ?? [];
            result.WatchOuts = GetStringList(root, "watch_outs")
                ?? GetStringList(root, "watchOuts")
                ?? GetStringList(root, "需要注意")
                ?? GetStringList(root, "caveats")
                ?? [];
            result.FollowUps = GetStringList(root, "follow_ups")
                ?? GetStringList(root, "followUps")
                ?? GetStringList(root, "followup")
                ?? GetStringList(root, "questions")
                ?? [];
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
            if (!string.IsNullOrWhiteSpace(s)) list.Add(s!);
        }
        return list;
    }
}
