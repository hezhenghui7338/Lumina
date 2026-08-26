using Lumina.Features.Reader;
using Xunit;

namespace Lumina.Tests;

public class SelectionActionPolicyTests
{
    [Fact]
    public void CapturedQuote_rejects_blank()
    {
        Assert.Null(SelectionActionPolicy.CapturedQuote(null));
        Assert.Null(SelectionActionPolicy.CapturedQuote(""));
        Assert.Null(SelectionActionPolicy.CapturedQuote("  \n\t"));
        Assert.False(SelectionActionPolicy.ShouldShowMenu("   "));
    }

    [Fact]
    public void CapturedQuote_trims_selected_text()
    {
        Assert.Equal("反向传播", SelectionActionPolicy.CapturedQuote("  反向传播  "));
        Assert.True(SelectionActionPolicy.ShouldShowMenu("  反向传播  "));
    }
}
