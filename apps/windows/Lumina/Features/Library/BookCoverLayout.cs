using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Media;
using Windows.UI;
using Lumina.Services;

namespace Lumina.Features.Library;

public static class BookCoverLayout
{
    public static SolidColorBrush BrushFor(string? category)
    {
        var (r, g, b) = BookCoverPalette.Rgb(category);
        return new SolidColorBrush(Color.FromArgb(255, r, g, b));
    }

    public static Visibility AuthorVisibility(string? author) =>
        string.IsNullOrWhiteSpace(author) ? Visibility.Collapsed : Visibility.Visible;
}
