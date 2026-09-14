using Lumina.Features.Reader;
using Xunit;

namespace Lumina.Tests;

public class ReaderBodyTypographyTests
{
    [Fact]
    public void CollapseEmptyLines_drops_blank_rows_from_div_noise()
    {
        var raw = "第一段内容。\n\n第二段内容。\n\n\n第三段内容。";
        Assert.Equal(
            "第一段内容。\n第二段内容。\n第三段内容。",
            ReaderBodyTypography.CollapseEmptyLines(raw));
    }

    [Fact]
    public void DisplayText_preserves_raw_when_highlighting()
    {
        var raw = "甲\n\n乙";
        Assert.Equal(raw, ReaderBodyTypography.DisplayText(raw, preservingHighlight: true));
        Assert.Equal("甲\n乙", ReaderBodyTypography.DisplayText(raw, preservingHighlight: false));
    }
}
