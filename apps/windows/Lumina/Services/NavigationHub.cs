namespace Lumina.Services;

/// <summary>Cross-page navigation intents (search / notes → reader).</summary>
public static class NavigationHub
{
    public static event Action<string, string, int?>? OpenBookRequested;
    public static event Action? OpenAllNotesRequested;
    public static event Action? OpenSearchRequested;
    public static event Action? OpenTaskManagerRequested;

    public static void RequestOpenBook(string bookId, string title, int? segmentIndex = null) =>
        OpenBookRequested?.Invoke(bookId, title, segmentIndex);

    public static void RequestAllNotes() => OpenAllNotesRequested?.Invoke();

    public static void RequestSearch() => OpenSearchRequested?.Invoke();

    public static void RequestTaskManager() => OpenTaskManagerRequested?.Invoke();
}
