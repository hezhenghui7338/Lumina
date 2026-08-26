namespace Lumina.Design;

/// Reading-surface paper only. Does not change the app Light/Dark setting.
public enum ReaderPaperKind
{
    White,
    Ivory,
    Sage,
    Night,
}

public readonly record struct ReaderPaperSwatch(
    byte PageR, byte PageG, byte PageB,
    byte TextR, byte TextG, byte TextB,
    byte SecondaryR, byte SecondaryG, byte SecondaryB);

public static class ReaderPaper
{
    public static readonly ReaderPaperKind[] All =
        [ReaderPaperKind.White, ReaderPaperKind.Ivory, ReaderPaperKind.Sage, ReaderPaperKind.Night];

    public static string Label(ReaderPaperKind kind) => kind switch
    {
        ReaderPaperKind.Ivory => "象牙",
        ReaderPaperKind.Sage => "护眼",
        ReaderPaperKind.Night => "夜间",
        _ => "白",
    };

    public static string RawValue(ReaderPaperKind kind) => kind switch
    {
        ReaderPaperKind.Ivory => "ivory",
        ReaderPaperKind.Sage => "sage",
        ReaderPaperKind.Night => "night",
        _ => "white",
    };

    public static ReaderPaperKind Parse(string? raw) => raw switch
    {
        "ivory" => ReaderPaperKind.Ivory,
        "sage" => ReaderPaperKind.Sage,
        "night" => ReaderPaperKind.Night,
        _ => ReaderPaperKind.White,
    };

    public static bool UsesLightText(ReaderPaperKind kind) => kind == ReaderPaperKind.Night;

    /// RGB aligned with macOS ThemeManager.ReaderPaper.
    public static ReaderPaperSwatch Swatch(ReaderPaperKind kind) => kind switch
    {
        ReaderPaperKind.Ivory => new(250, 242, 224, 56, 41, 26, 107, 89, 71),
        ReaderPaperKind.Sage => new(237, 242, 230, 41, 56, 46, 97, 115, 102),
        ReaderPaperKind.Night => new(26, 26, 31, 242, 242, 247, 166, 166, 179),
        _ => new(255, 255, 255, 28, 28, 30, 110, 110, 115),
    };
}
