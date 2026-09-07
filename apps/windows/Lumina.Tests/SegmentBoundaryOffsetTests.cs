using Lumina.Features.Reader;
using Xunit;

namespace Lumina.Tests;

public class SegmentBoundaryOffsetTests
{
    [Fact]
    public void UnicodeOffset_countsBmpAndSurrogatePair()
    {
        const string text = "学而😊时习";
        Assert.Equal(0, SegmentBoundaryOffset.UnicodeOffset(text, 0));
        Assert.Equal(2, SegmentBoundaryOffset.UnicodeOffset(text, 2));
        Assert.Equal(3, SegmentBoundaryOffset.UnicodeOffset(text, 4));
        Assert.Equal(2, SegmentBoundaryOffset.UnicodeOffset(text, 3));
        Assert.Equal(text.EnumerateRunes().Count(), SegmentBoundaryOffset.UnicodeOffset(text, text.Length));
    }

    [Fact]
    public void Utf16Index_roundTripsUnicodeOffset()
    {
        const string text = "左侧。😊右侧。";
        var total = text.EnumerateRunes().Count();
        for (var offset = 0; offset <= total; offset++)
        {
            var utf16 = SegmentBoundaryOffset.Utf16Index(text, offset);
            Assert.Equal(offset, SegmentBoundaryOffset.UnicodeOffset(text, utf16));
        }
    }

    [Fact]
    public void Split_preservesCoverageAndEmoji()
    {
        const string text = "左侧。😊右侧。";
        var (left, right) = SegmentBoundaryOffset.Split(text, 4);
        Assert.Equal("左侧。😊", left);
        Assert.Equal("右侧。", right);
        Assert.Equal(text, left + right);
    }

    [Fact]
    public void Split_clampsEnds()
    {
        var (emptyLeft, allRight) = SegmentBoundaryOffset.Split("abc", 0);
        Assert.Equal("", emptyLeft);
        Assert.Equal("abc", allRight);
        var (allLeft, emptyRight) = SegmentBoundaryOffset.Split("abc", 99);
        Assert.Equal("abc", allLeft);
        Assert.Equal("", emptyRight);
    }

    [Fact]
    public void AdjustDialog_previewsClickUntilSave()
    {
        var testsRoot = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", ".."));
        var path = Path.GetFullPath(Path.Combine(
            testsRoot, "..", "Lumina", "Features", "Reader", "ReaderPage.xaml.cs"));
        Assert.True(File.Exists(path), path);
        var source = File.ReadAllText(path);
        var method = source.Split("private async void AdjustBoundary_Click", 2)[1]
            .Split("private void ApplyBoundaryEvent", 2)[0];
        Assert.DoesNotContain("new Slider", method);
        Assert.DoesNotContain("拖动滑块", method);
        Assert.Contains("PrimaryButtonText = \"保存\"", method);
        Assert.Contains("点击正文中要作为新分界的位置", method);
        Assert.Contains("点「保存」才落库并重新摘要这两段", method);
        Assert.DoesNotContain("点击后立即保存并重新摘要这两段", method);
        Assert.Contains("SelectionStart", method);
        var clickHandler = method.Split("editor.PointerReleased", 2)[1]
            .Split("dlg.PrimaryButtonClick", 2)[0];
        Assert.DoesNotContain("MoveSegmentBoundaryAsync", clickHandler);
        Assert.Contains("MoveSegmentBoundaryAsync", method.Split("dlg.PrimaryButtonClick", 2)[1]);
    }

    [Fact]
    public void NearestOffset_picksClosestThenSmaller()
    {
        Assert.Equal(10, SegmentBoundaryOffset.NearestOffset(10, Array.Empty<int>()));
        Assert.Equal(8, SegmentBoundaryOffset.NearestOffset(10, [8, 14]));
        Assert.Equal(5, SegmentBoundaryOffset.NearestOffset(10, [5, 15]));
        Assert.Equal(15, SegmentBoundaryOffset.NearestOffset(12, [5, 15]));
    }

    [Fact]
    public void CanSave_requiresChangedInteriorCut()
    {
        Assert.False(SegmentBoundaryOffset.CanSave(12, 12, 40, false));
        Assert.False(SegmentBoundaryOffset.CanSave(20, 12, 40, true));
        Assert.False(SegmentBoundaryOffset.CanSave(0, 12, 40, false));
        Assert.False(SegmentBoundaryOffset.CanSave(40, 12, 40, false));
        Assert.True(SegmentBoundaryOffset.CanSave(20, 12, 40, false));
    }
}
