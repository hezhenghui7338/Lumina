using Lumina.Services;

namespace Lumina.Features.Library;

/// Unselected toolbar summarize: whole library, or only the visible filter slice.
public static class LibrarySummarizeScope
{
    public static bool IsLibraryWide(bool facetsAreDefault, string? titleQuery) =>
        facetsAreDefault && string.IsNullOrWhiteSpace(titleQuery);

    /// <summary>
    /// Null means POST /books/summarize/start with no book_ids (library-wide).
    /// Empty means the current slice has nothing startable — do not POST (core treats [] as all).
    /// Otherwise start only these visible, startable books.
    /// </summary>
    public static IReadOnlyList<string>? IdsForUnselectedStart(
        IReadOnlyList<BookSummary> visible,
        bool libraryWide)
    {
        if (libraryWide) return null;
        return visible.Where(b => b.CanStartSummarize).Select(b => b.Id).ToList();
    }
}
