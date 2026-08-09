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
    }
}
