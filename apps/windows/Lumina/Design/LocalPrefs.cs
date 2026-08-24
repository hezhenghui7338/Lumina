using System.Text.Json;

namespace Lumina.Design;

/// <summary>File-based prefs under %APPDATA%\Lumina (works unpackaged).</summary>
public static class LocalPrefs
{
    private static readonly string Path = System.IO.Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
        "Lumina",
        "ui-prefs.json");

    private static PrefsData _data = Load();

    public static string Theme
    {
        get => _data.Theme;
        set
        {
            _data.Theme = value;
            Save();
        }
    }

    public static bool OnboardingDone
    {
        get => _data.OnboardingDone;
        set
        {
            _data.OnboardingDone = value;
            Save();
        }
    }

    public static double ReaderFontSize
    {
        get => _data.ReaderFontSize <= 0 ? 15 : _data.ReaderFontSize;
        set
        {
            _data.ReaderFontSize = value;
            Save();
        }
    }

    public static bool GetShowRaw(string bookId) =>
        _data.ShowRawByBook.TryGetValue(bookId, out var v) && v;

    public static void SetShowRaw(string bookId, bool showRaw)
    {
        _data.ShowRawByBook[bookId] = showRaw;
        Save();
    }

    public static int? GetReadingProgress(string bookId, int segmentCount)
    {
        if (_data.ReadingProgressByBook.TryGetValue(bookId, out var cached)
            && cached.SegmentCount == segmentCount)
        {
            return cached.Index;
        }
        return null;
    }

    public static double GetReadingProgressOffset(string bookId, int segmentCount)
    {
        if (_data.ReadingProgressByBook.TryGetValue(bookId, out var cached)
            && cached.SegmentCount == segmentCount)
        {
            return Math.Max(0, cached.OffsetY);
        }
        return 0;
    }

    public readonly record struct CachedReadingProgress(
        int Index,
        int SegmentCount,
        double OffsetY,
        double? Percent);

    public static CachedReadingProgress? GetCachedProgress(string bookId)
    {
        if (!_data.ReadingProgressByBook.TryGetValue(bookId, out var cached))
            return null;
        return new CachedReadingProgress(cached.Index, cached.SegmentCount, cached.OffsetY, cached.Percent);
    }

    public static void ClearCachedProgress(string bookId)
    {
        if (_data.ReadingProgressByBook.Remove(bookId))
            Save();
    }

    public static void SetReadingProgress(
        string bookId,
        int index,
        int segmentCount,
        double offsetY = 0,
        double? percent = null)
    {
        _data.ReadingProgressByBook[bookId] = new ProgressPref
        {
            Index = index,
            SegmentCount = segmentCount,
            OffsetY = Math.Max(0, offsetY),
            Percent = percent,
        };
        Save();
    }

    private static PrefsData Load()
    {
        try
        {
            if (File.Exists(Path))
                return JsonSerializer.Deserialize<PrefsData>(File.ReadAllText(Path)) ?? new PrefsData();
        }
        catch { /* ignore */ }
        return new PrefsData();
    }

    private static void Save()
    {
        try
        {
            Directory.CreateDirectory(System.IO.Path.GetDirectoryName(Path)!);
            File.WriteAllText(Path, JsonSerializer.Serialize(_data));
        }
        catch { /* ignore */ }
    }

    private sealed class PrefsData
    {
        public string Theme { get; set; } = "Light";
        public bool OnboardingDone { get; set; }
        public double ReaderFontSize { get; set; } = 15;
        public Dictionary<string, bool> ShowRawByBook { get; set; } = new();
        public Dictionary<string, ProgressPref> ReadingProgressByBook { get; set; } = new();
    }

    private sealed class ProgressPref
    {
        public int Index { get; set; }
        public int SegmentCount { get; set; }
        public double OffsetY { get; set; }
        public double? Percent { get; set; }
    }
}
