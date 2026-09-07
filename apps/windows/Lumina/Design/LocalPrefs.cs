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

    public static string ReaderPaperRaw
    {
        get => string.IsNullOrWhiteSpace(_data.ReaderPaper) ? "white" : _data.ReaderPaper;
        set
        {
            _data.ReaderPaper = value ?? "white";
            Save();
        }
    }

    public static double ReaderFontScale
    {
        get => _data.ReaderFontScale <= 0 ? 1.0 : _data.ReaderFontScale;
        set
        {
            _data.ReaderFontScale = value;
            Save();
        }
    }

    public static string LibrarySummary
    {
        get => string.IsNullOrWhiteSpace(_data.LibrarySummary) ? "all" : _data.LibrarySummary;
        set { _data.LibrarySummary = value; Save(); }
    }

    public static string LibraryReading
    {
        get => string.IsNullOrWhiteSpace(_data.LibraryReading) ? "all" : _data.LibraryReading;
        set { _data.LibraryReading = value; Save(); }
    }

    public static string LibraryCategory
    {
        get => string.IsNullOrWhiteSpace(_data.LibraryCategory) ? "all" : _data.LibraryCategory;
        set { _data.LibraryCategory = value; Save(); }
    }

    public static bool LibraryFavoriteOnly
    {
        get => _data.LibraryFavoriteOnly;
        set { _data.LibraryFavoriteOnly = value; Save(); }
    }

    public static string LibrarySort
    {
        get => string.IsNullOrWhiteSpace(_data.LibrarySort) ? "recent" : _data.LibrarySort;
        set { _data.LibrarySort = value; Save(); }
    }

    public static string LibrarySortOrder
    {
        get => _data.LibrarySortOrder ?? "";
        set { _data.LibrarySortOrder = value; Save(); }
    }

    public static bool LibraryGridMode
    {
        get => _data.LibraryGridMode;
        set { _data.LibraryGridMode = value; Save(); }
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

    public static float ListenRate
    {
        get => _data.ListenRate <= 0 ? 1.0f : _data.ListenRate;
        set
        {
            _data.ListenRate = value;
            Save();
        }
    }

    public static string ListenSystemVoiceId
    {
        get => _data.ListenSystemVoiceId ?? "";
        set
        {
            _data.ListenSystemVoiceId = value ?? "";
            Save();
        }
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
        public double ReaderFontScale { get; set; } = 1.0;
        public string ReaderPaper { get; set; } = "white";
        public string LibrarySummary { get; set; } = "all";
        public string LibraryReading { get; set; } = "all";
        public string LibraryCategory { get; set; } = "all";
        public bool LibraryFavoriteOnly { get; set; }
        public string LibrarySort { get; set; } = "recent";
        public string LibrarySortOrder { get; set; } = "";
        public bool LibraryGridMode { get; set; } = true;
        public Dictionary<string, bool> ShowRawByBook { get; set; } = new();
        public Dictionary<string, ProgressPref> ReadingProgressByBook { get; set; } = new();
        public float ListenRate { get; set; } = 1.0f;
        public string ListenSystemVoiceId { get; set; } = "";
    }

    private sealed class ProgressPref
    {
        public int Index { get; set; }
        public int SegmentCount { get; set; }
        public double OffsetY { get; set; }
        public double? Percent { get; set; }
    }
}
