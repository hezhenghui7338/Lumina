using Lumina.Design;
using Lumina.Features.Library;
using Lumina.Features.Reader;
using Lumina.Features.Settings;
using Lumina.Services;
using Xunit;

namespace Lumina.Tests;

public class WindowsParityPolicyTests
{
    [Fact]
    public void SummarizeActivity_hides_when_idle_and_labels_stall()
    {
        Assert.False(SummarizeActivityPolicy.ShouldShow(0));
        Assert.True(SummarizeActivityPolicy.ShouldShow(2));
        Assert.Equal(LibraryCollections.Summarizing, SummarizeActivityPolicy.DestinationCollection);
        Assert.Equal(
            "3 排队 · 1 建索引 · 正在建索引",
            SummarizeActivityPolicy.StatusLabel(0, 3, 1, "indexing"));
        Assert.DoesNotContain("0 进行中", SummarizeActivityPolicy.StatusLabel(0, 3, 1, "indexing"));
    }

    [Fact]
    public void ChatCitation_does_not_auto_jump_and_labels_segment()
    {
        Assert.False(ChatCitationJumpPolicy.AutoJumpOnComplete);
        Assert.Equal("[段 3]", ChatCitationJumpPolicy.ButtonLabel(2, null));
        Assert.Equal("[段 3 · 学而]", ChatCitationJumpPolicy.ButtonLabel(2, "学而"));
        Assert.Equal(2, ChatCitationJumpPolicy.TargetIdx(2));
        Assert.Null(ChatCitationJumpPolicy.TargetIdx(-1));
        Assert.Equal("[段 1]", new ChatCitation { SegmentIndex = 0 }.ButtonLabel);
    }

    [Fact]
    public void NeighborPrefetch_returns_prev_and_next_only()
    {
        int[] sorted = [0, 2, 5];
        Assert.Equal(new[] { 0, 5 }, NeighborPrefetchPolicy.Neighbors(2, sorted));
        Assert.Equal(new[] { 2 }, NeighborPrefetchPolicy.Neighbors(0, sorted));
        Assert.Empty(NeighborPrefetchPolicy.Neighbors(9, sorted));
        Assert.True(NeighborPrefetchPolicy.NeedsRawText(true));
        Assert.True(NeighborPrefetchPolicy.NeedsSummaryJson(false));
    }

    [Fact]
    public void SegmentCatalog_groups_by_chapter_and_collapses()
    {
        var segments = new List<SegmentRow>
        {
            new() { Idx = 0, Chapter = "第一章", Label = "引子" },
            new() { Idx = 1, Chapter = "第一章", Label = "科举" },
            new() { Idx = 2, Chapter = "第二章", Label = "入京" },
        };
        Assert.True(SegmentCatalogPolicy.ShouldGroup(segments));
        var open = SegmentCatalogPolicy.Build(segments, new HashSet<string>());
        Assert.Equal(5, open.Count);
        Assert.True(open[0].IsHeader);
        Assert.Contains("§ 第一章", open[0].HeaderText);
        Assert.Equal(2, open[0].HeaderCount);
        Assert.False(open[1].IsHeader);
        Assert.Equal(0, open[1].Segment!.Idx);

        var collapsed = SegmentCatalogPolicy.Build(segments, new HashSet<string> { "第一章" });
        Assert.Equal(3, collapsed.Count);
        Assert.True(collapsed[0].IsCollapsed);
        Assert.True(collapsed[1].IsHeader);
        Assert.Equal(2, collapsed[2].Segment!.Idx);
        Assert.True(collapsed[0].TitleSize < collapsed.First(i => !i.IsHeader).TitleSize);
        Assert.Equal(0, collapsed[0].PreviewSize);
    }

    [Fact]
    public void SegmentCatalog_flat_when_no_chapters()
    {
        var segments = new List<SegmentRow>
        {
            new() { Idx = 0, Label = "a" },
            new() { Idx = 1, Label = "b" },
        };
        Assert.False(SegmentCatalogPolicy.ShouldGroup(segments));
        var items = SegmentCatalogPolicy.Build(segments, new HashSet<string>());
        Assert.Equal(2, items.Count);
        Assert.All(items, i => Assert.False(i.IsHeader));
    }

    [Fact]
    public void LibraryImportPolicy_accepts_common_ebook_extensions()
    {
        Assert.True(LibraryImportPolicy.IsSupportedPath(@"C:\books\foo.epub"));
        Assert.True(LibraryImportPolicy.IsSupportedPath("bar.PDF"));
        Assert.False(LibraryImportPolicy.IsSupportedPath("photo.png"));
        Assert.False(LibraryImportPolicy.IsSupportedPath(""));
    }

    [Fact]
    public void BookSummary_cancel_flags_follow_processing_kind()
    {
        var ingest = new BookSummary { Status = "processing", ProcessingKind = "ingest" };
        var resegment = new BookSummary { Status = "processing", ProcessingKind = "resegment", SegmentCount = 8 };
        var ready = new BookSummary { Status = "unread", SegmentCount = 8 };
        Assert.True(ingest.CanCancelIngest);
        Assert.False(ingest.CanCancelResegment);
        Assert.True(resegment.CanCancelResegment);
        Assert.False(resegment.CanCancelIngest);
        Assert.False(resegment.CanResegment);
        Assert.True(ready.CanResegment);
    }

    [Fact]
    public void ReadingFontScale_has_five_steps()
    {
        Assert.Equal(5, ReadingFontScale.Steps.Length);
        Assert.Equal(15, ReadingFontScale.Size(1.0), 3);
        Assert.Equal("较大", ReadingFontScale.Label(1.15));
        Assert.Equal(1.15, ReadingFontScale.Step(1.0, 1));
        Assert.False(ReadingFontScale.CanDecrease(0.85));
        Assert.False(ReadingFontScale.CanIncrease(1.45));
    }

    [Fact]
    public void ReaderPaper_parses_four_kinds()
    {
        Assert.Equal(ReaderPaperKind.Ivory, ReaderPaper.Parse("ivory"));
        Assert.Equal("护眼", ReaderPaper.Label(ReaderPaperKind.Sage));
        Assert.True(ReaderPaper.UsesLightText(ReaderPaperKind.Night));
        Assert.False(ReaderPaper.UsesLightText(ReaderPaperKind.White));
        Assert.Equal(4, ReaderPaper.All.Length);
    }

    [Fact]
    public void CustomResourceDraft_rejects_builtin_and_bad_url()
    {
        Assert.NotNull(CustomResourceDraft.Validate("openai", "https://x.com/v1", "m"));
        Assert.NotNull(CustomResourceDraft.Validate("my llm", "https://x.com/v1", "m"));
        Assert.NotNull(CustomResourceDraft.Validate("mine", "not-a-url", "m"));
        Assert.Null(CustomResourceDraft.Validate("mine", "https://api.example.com/v1", "gpt-4o-mini"));
        var built = CustomResourceDraft.Build("mine", "https://api.example.com/v1", "gpt-4o-mini", "", "k");
        Assert.Equal("openai", built.Provider);
        Assert.Equal("k", built.ApiKey);
        Assert.False(CustomResourceDraft.CanDelete("openai"));
        Assert.True(CustomResourceDraft.CanDelete("mine"));
        var resources = new List<ModelResourceSettings> { built, new() { Id = "ollama" } };
        var chat = new List<string> { "mine", "openai" };
        var summarize = new List<string> { "ollama", "mine" };
        CustomResourceDraft.Detach(resources, chat, summarize, "mine");
        Assert.DoesNotContain(resources, r => r.Id == "mine");
        Assert.Equal(new[] { "openai" }, chat);
        Assert.Equal(new[] { "ollama" }, summarize);
        CustomResourceDraft.Detach(resources, chat, summarize, "ollama");
        Assert.Contains(resources, r => r.Id == "ollama");
    }

    [Fact]
    public void LibrarySummarizeScope_null_means_whole_library_empty_means_skip()
    {
        var idle = new BookSummary
        {
            Id = "a",
            Status = "unread",
            SummaryTotalCount = 4,
            SummaryReadyCount = 0,
            SummarizeState = "idle",
        };
        var done = new BookSummary
        {
            Id = "b",
            Status = "unread",
            SummaryTotalCount = 4,
            SummaryReadyCount = 4,
            SummarizeState = "idle",
        };
        Assert.True(LibrarySummarizeScope.IsLibraryWide(true, ""));
        Assert.False(LibrarySummarizeScope.IsLibraryWide(true, "论语"));
        Assert.False(LibrarySummarizeScope.IsLibraryWide(false, ""));
        Assert.Null(LibrarySummarizeScope.IdsForUnselectedStart([idle], libraryWide: true));
        Assert.Equal(new[] { "a" }, LibrarySummarizeScope.IdsForUnselectedStart([idle, done], libraryWide: false));
        var none = LibrarySummarizeScope.IdsForUnselectedStart([done], libraryWide: false);
        Assert.NotNull(none);
        Assert.Empty(none);
    }

    [Fact]
    public void LibraryImportPolicy_collects_supported_files_from_folder()
    {
        var root = Path.Combine(AppContext.BaseDirectory, "lumina-import-" + Guid.NewGuid().ToString("N"));
        var nested = Path.Combine(root, "ch");
        Directory.CreateDirectory(nested);
        try
        {
            File.WriteAllText(Path.Combine(root, "a.epub"), "x");
            File.WriteAllText(Path.Combine(root, "skip.png"), "x");
            File.WriteAllText(Path.Combine(nested, "b.txt"), "x");
            File.WriteAllText(Path.Combine(root, ".hidden.md"), "x");
            var found = LibraryImportPolicy.CollectFromFolder(root);
            Assert.Equal(2, found.Count);
            Assert.Contains(found, p => p.EndsWith("a.epub", StringComparison.OrdinalIgnoreCase));
            Assert.Contains(found, p => p.EndsWith("b.txt", StringComparison.OrdinalIgnoreCase));

            var mixed = LibraryImportPolicy.CollectImportPaths(
                ["photo.png", Path.Combine(root, "a.epub")],
                [nested]);
            Assert.Contains(mixed, p => p.EndsWith("a.epub", StringComparison.OrdinalIgnoreCase));
            Assert.Contains(mixed, p => p.EndsWith("b.txt", StringComparison.OrdinalIgnoreCase));
            Assert.DoesNotContain(mixed, p => p.EndsWith("skip.png", StringComparison.OrdinalIgnoreCase));
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public void LibraryNavArgs_open_import_defaults_false()
    {
        Assert.False(new LibraryNavArgs().OpenImport);
        Assert.True(new LibraryNavArgs(true).OpenImport);
    }
}
