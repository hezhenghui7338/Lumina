using Lumina.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace Lumina.Features.Shared;

internal static class ChunkTargetField
{
    public static NumberBox MakeBox(string header, int min, int max, int value) => new()
    {
        Header = header,
        Value = value,
        Minimum = min,
        Maximum = max,
        SpinButtonPlacementMode = NumberBoxSpinButtonPlacementMode.Hidden,
        ValidationMode = NumberBoxValidationMode.InvalidInputOverwritten,
        Width = 160,
    };

    public static void AttachPresets(NumberBox box, Panel host, int min, int max)
    {
        host.Children.Clear();
        var buttons = new List<Button>();

        void Refresh()
        {
            var current = double.IsNaN(box.Value) ? int.MinValue : (int)Math.Round(box.Value);
            var accent = AccentStyle();
            foreach (var btn in buttons)
            {
                var preset = (int)btn.Tag;
                btn.Style = current == preset ? accent : null;
            }
        }

        foreach (var preset in ResegmentTarget.Presets)
        {
            if (preset < min || preset > max) continue;
            var btn = new Button
            {
                Content = preset.ToString(),
                Tag = preset,
                MinWidth = 56,
                VerticalAlignment = VerticalAlignment.Bottom,
            };
            btn.Click += (_, _) =>
            {
                box.Value = preset;
                Refresh();
            };
            buttons.Add(btn);
            host.Children.Add(btn);
        }

        box.ValueChanged += (_, _) => Refresh();
        Refresh();
    }

    public static StackPanel MakePresetRow(NumberBox box, int min, int max)
    {
        var row = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 6,
            VerticalAlignment = VerticalAlignment.Bottom,
        };
        AttachPresets(box, row, min, max);
        return row;
    }

    public static int ReadClamped(NumberBox box, int fallback, int min, int max)
    {
        var raw = double.IsNaN(box.Value) ? fallback : box.Value;
        return (int)Math.Clamp(raw, min, max);
    }

    private static Style? AccentStyle()
    {
        return Application.Current?.Resources.TryGetValue("AccentButtonStyle", out var style) == true
            ? style as Style
            : null;
    }
}
