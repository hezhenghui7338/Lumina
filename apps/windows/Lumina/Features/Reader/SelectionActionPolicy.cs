namespace Lumina.Features.Reader;

/// Whether a finished text selection should raise the copy / write-idea menu.
public static class SelectionActionPolicy
{
    public static string? CapturedQuote(string? selectedText)
    {
        if (string.IsNullOrWhiteSpace(selectedText)) return null;
        return selectedText.Trim();
    }

    public static bool ShouldShowMenu(string? selectedText) =>
        CapturedQuote(selectedText) is not null;
}
