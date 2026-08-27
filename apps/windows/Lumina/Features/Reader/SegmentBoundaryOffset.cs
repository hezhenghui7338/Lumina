using System.Collections.Generic;
using System.Linq;

namespace Lumina.Features.Reader;

/// <summary>
/// Maps UTF-16 caret indices to Python <c>len(str)</c> / Unicode scalar offsets
/// used by <c>POST .../boundary</c> <c>left_char_count</c>.
/// </summary>
public static class SegmentBoundaryOffset
{
    public static int UnicodeOffset(string text, int utf16Index)
    {
        if (string.IsNullOrEmpty(text)) return 0;
        var index = Math.Clamp(utf16Index, 0, text.Length);
        if (index > 0 && index < text.Length && char.IsLowSurrogate(text[index]))
            index--;
        return text[..index].EnumerateRunes().Count();
    }

    public static int Utf16Index(string text, int unicodeOffset)
    {
        if (string.IsNullOrEmpty(text) || unicodeOffset <= 0) return 0;
        var remaining = unicodeOffset;
        var utf16 = 0;
        foreach (var rune in text.EnumerateRunes())
        {
            if (remaining <= 0) break;
            utf16 += rune.Utf16SequenceLength;
            remaining--;
        }
        return utf16;
    }

    public static (string Left, string Right) Split(string text, int unicodeOffset)
    {
        text ??= "";
        if (unicodeOffset <= 0) return ("", text);
        var utf16 = Utf16Index(text, unicodeOffset);
        if (utf16 >= text.Length) return (text, "");
        return (text[..utf16], text[utf16..]);
    }

    /// <summary>
    /// Matches Python <c>snap_cut_offset</c>: nearest candidate, ties go to the smaller offset.
    /// </summary>
    public static int NearestOffset(int offset, IReadOnlyList<int> candidates)
    {
        if (candidates is null || candidates.Count == 0) return offset;
        var best = candidates[0];
        var bestKey = (Math.Abs(best - offset), best);
        for (var i = 1; i < candidates.Count; i++)
        {
            var item = candidates[i];
            var key = (Math.Abs(item - offset), item);
            if (key.CompareTo(bestKey) < 0)
            {
                best = item;
                bestKey = key;
            }
        }
        return best;
    }

    public static bool CanSave(int previewCut, int originalCut, int totalChars, bool isSaving) =>
        !isSaving && previewCut != originalCut && previewCut > 0 && previewCut < totalChars;
}
