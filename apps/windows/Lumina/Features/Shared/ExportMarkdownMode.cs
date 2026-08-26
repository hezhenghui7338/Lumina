namespace Lumina.Features.Shared;

internal static class ExportMarkdownMode
{
    public const string Full = "full";
    public const string Sentences = "sentences";

    public static bool AllowsNotes(string mode) => mode != Sentences;

    public static string DefaultFilename(string title, string mode)
    {
        var suffix = mode == Sentences ? "总结" : "summary";
        return $"{Sanitize(title)}-{suffix}.md";
    }

    internal static string Sanitize(string title)
    {
        var invalid = Path.GetInvalidFileNameChars();
        var cleaned = string.Concat(title.Select(c => invalid.Contains(c) ? '-' : c)).Trim();
        return string.IsNullOrEmpty(cleaned) ? "summary" : cleaned;
    }
}
