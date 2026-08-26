using Lumina.Features.Shared;
using Xunit;

namespace Lumina.Tests;

public class ExportMarkdownModeTests
{
    [Fact]
    public void Sentences_mode_omits_notes_and_uses_brief_filename()
    {
        Assert.Equal("full", ExportMarkdownMode.Full);
        Assert.Equal("sentences", ExportMarkdownMode.Sentences);
        Assert.True(ExportMarkdownMode.AllowsNotes(ExportMarkdownMode.Full));
        Assert.False(ExportMarkdownMode.AllowsNotes(ExportMarkdownMode.Sentences));
        Assert.Equal("三体-summary.md", ExportMarkdownMode.DefaultFilename("三体", ExportMarkdownMode.Full));
        Assert.Equal("三体-总结.md", ExportMarkdownMode.DefaultFilename("三体", ExportMarkdownMode.Sentences));
    }

    [Fact]
    public void Filename_strips_invalid_characters()
    {
        Assert.Equal("a-b-summary.md", ExportMarkdownMode.DefaultFilename("a/b", ExportMarkdownMode.Full));
        Assert.Equal("summary-summary.md", ExportMarkdownMode.DefaultFilename("   ", ExportMarkdownMode.Full));
    }
}
