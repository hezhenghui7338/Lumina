namespace Lumina.Features.Library;

/// File types the Windows picker / drag-drop importer accepts (B1).
public static class LibraryImportPolicy
{
    public const int MaxDropFiles = 200;
    public const int MaxWalkDirectories = 400;

    public static readonly string[] Extensions =
    [
        ".pdf", ".epub", ".mobi", ".azw", ".azw3",
        ".txt", ".text", ".md", ".markdown", ".mdown", ".mkd", ".log",
        ".html", ".htm", ".xhtml", ".rtf", ".docx", ".odt", ".fb2",
    ];

    public static bool IsSupportedPath(string? path)
    {
        if (string.IsNullOrWhiteSpace(path)) return false;
        var ext = Path.GetExtension(path.Trim());
        return Extensions.Contains(ext, StringComparer.OrdinalIgnoreCase);
    }

    public static IReadOnlyList<string> CollectImportPaths(
        IEnumerable<string> filePaths,
        IEnumerable<string>? folderPaths = null,
        int maxFiles = MaxDropFiles)
    {
        var found = new List<string>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var path in filePaths)
        {
            if (!IsSupportedPath(path) || !seen.Add(path)) continue;
            found.Add(path);
            if (found.Count >= maxFiles) return found;
        }
        if (folderPaths is null) return found;
        foreach (var folder in folderPaths)
        {
            foreach (var path in CollectFromFolder(folder, maxFiles - found.Count))
            {
                if (!seen.Add(path)) continue;
                found.Add(path);
                if (found.Count >= maxFiles) return found;
            }
        }
        return found;
    }

    /// Walk a folder (including subfolders) and collect supported files, capped so a huge tree cannot freeze UI.
    public static IReadOnlyList<string> CollectFromFolder(string? folderPath, int maxFiles = MaxDropFiles)
    {
        if (maxFiles <= 0 || string.IsNullOrWhiteSpace(folderPath) || !Directory.Exists(folderPath))
            return [];
        var found = new List<string>();
        var pending = new Stack<string>();
        pending.Push(folderPath);
        var walked = 0;
        while (pending.Count > 0 && found.Count < maxFiles && walked < MaxWalkDirectories)
        {
            var dir = pending.Pop();
            walked++;
            try
            {
                foreach (var file in Directory.EnumerateFiles(dir))
                {
                    var name = Path.GetFileName(file);
                    if (name.StartsWith('.')) continue;
                    if (!IsSupportedPath(file)) continue;
                    found.Add(file);
                    if (found.Count >= maxFiles) return found;
                }
                foreach (var sub in Directory.EnumerateDirectories(dir))
                {
                    var name = Path.GetFileName(sub);
                    if (name.StartsWith('.')) continue;
                    pending.Push(sub);
                }
            }
            catch (UnauthorizedAccessException)
            {
            }
            catch (IOException)
            {
            }
        }
        return found;
    }
}
