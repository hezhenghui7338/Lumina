using Lumina.Features.Reader.Listen;
using Xunit;

namespace Lumina.Tests;

public class ListenScriptTests
{
    private const string SampleJson = """
        {"sentences":["本段交代主角出身寒门。","邻里敬其向学却无力资助。"],"bullets":[{"label":"寒门出身","body":"主角生于贫苦农家，父亲早逝。"},{"label":"赴考之志","body":"段末以金榜题名收束。"},{"label":"邻里期望","body":"乡邻视为村庄的希望。"}],"notes":["后文将出现权谋冲突。"],"follow_ups":["主角与邻里期望之间有何张力？"],"label":"引子","anchor":"§第一章 · 段 1"}
        """;

    [Fact]
    public void Summary_layer_labels_brief_and_full()
    {
        Assert.Equal("听简要摘要", ListenScriptBuilder.Label(ListenMode.Summary));
        Assert.Equal("听完整摘要", ListenScriptBuilder.Label(ListenMode.Detailed));
        Assert.Equal("简要摘要", ListenScriptBuilder.ShortLabel(ListenMode.Summary));
        Assert.Equal("完整摘要", ListenScriptBuilder.ShortLabel(ListenMode.Detailed));
    }

    [Fact]
    public void Summary_mode_is_sentences_only()
    {
        var script = ListenScriptBuilder.Build(ListenMode.Summary, SampleJson, null);
        Assert.True(script.Ready);
        Assert.Equal(
            new[] { "本段交代主角出身寒门。", "邻里敬其向学却无力资助。" },
            script.Texts);
        var joined = string.Join("\n", script.Texts);
        Assert.DoesNotContain("你可以接着问", joined);
        Assert.DoesNotContain("主角与邻里期望之间有何张力？", joined);
        Assert.DoesNotContain(ListenScript.SectionBullets, joined);
    }

    [Fact]
    public void Detailed_mode_includes_bullets_not_notes_or_follow_ups()
    {
        var script = ListenScriptBuilder.Build(ListenMode.Detailed, SampleJson, null);
        Assert.True(script.Ready);
        Assert.Equal("本段交代主角出身寒门。", script.Texts[0]);
        Assert.Contains(ListenScript.SectionBullets, script.Texts);
        Assert.Contains("1. 寒门出身。主角生于贫苦农家，父亲早逝。", script.Texts);
        Assert.Contains("2. 赴考之志。段末以金榜题名收束。", script.Texts);
        Assert.DoesNotContain(ListenScript.SectionNotes, script.Texts);
        Assert.DoesNotContain("后文将出现权谋冲突。", script.Texts);
        var joined = string.Join("\n", script.Texts);
        Assert.DoesNotContain("你可以接着问", joined);
        Assert.DoesNotContain("主角与邻里期望之间有何张力？", joined);
    }

    [Fact]
    public void Original_splits_sentences()
    {
        var script = ListenScriptBuilder.Build(
            ListenMode.Original, null, "第一句。第二句！第三句？");
        Assert.True(script.Ready);
        Assert.Equal("第一句。", script.Texts[0]);
        Assert.Contains("第二句！", script.Texts);
        Assert.Contains("第三句？", script.Texts);
    }

    [Fact]
    public void Missing_summary_is_not_ready()
    {
        var script = ListenScriptBuilder.Build(ListenMode.Summary, null, null);
        Assert.False(script.Ready);
        Assert.Equal("summary_not_ready", script.SkipReason);
        Assert.Empty(script.Texts);
    }

    [Fact]
    public void Empty_original_is_not_ready()
    {
        var script = ListenScriptBuilder.Build(ListenMode.Original, null, "   ");
        Assert.False(script.Ready);
        Assert.Equal("empty_text", script.SkipReason);
    }

    [Fact]
    public void Detects_language()
    {
        Assert.Equal("zh", ListenScriptBuilder.DetectLanguage("本段交代主角出身寒门。"));
        Assert.Equal("en", ListenScriptBuilder.DetectLanguage("The hero leaves home at dawn."));
    }

    [Fact]
    public void Speaker_follows_visible_panel_not_only_the_picker()
    {
        Assert.False(ListenChromePolicy.IsShowingOriginal(false, false, false));
        Assert.True(ListenChromePolicy.IsShowingOriginal(false, true, false));
        Assert.True(ListenChromePolicy.IsShowingOriginal(true, true, false));
        Assert.False(ListenChromePolicy.IsShowingOriginal(true, true, true));
        Assert.Equal(ListenMode.Summary, ListenChromePolicy.PrimaryMode(false));
        Assert.Equal(ListenMode.Original, ListenChromePolicy.PrimaryMode(true));
        Assert.True(ListenChromePolicy.ShowsSummaryChevron(false));
        Assert.False(ListenChromePolicy.ShowsSummaryChevron(true));
    }
}

public class ListenAdvancePolicyTests
{
    [Fact]
    public void Plays_ready_segment()
    {
        Assert.Equal(
            new ListenAdvanceDecision.Play(2),
            ListenAdvancePolicy.Decide(2, 10, true, null, 0));
    }

    [Fact]
    public void Skips_unready_then_continues()
    {
        Assert.Equal(
            new ListenAdvanceDecision.Skip(2, "summary_not_ready"),
            ListenAdvancePolicy.Decide(1, 10, false, "summary_not_ready", 0));
    }

    [Fact]
    public void Pauses_after_consecutive_skips()
    {
        Assert.Equal(
            new ListenAdvanceDecision.PauseTooManySkips(4),
            ListenAdvancePolicy.Decide(4, 10, false, "summary_not_ready", 2));
    }

    [Fact]
    public void Finishes_at_end()
    {
        Assert.Equal(
            new ListenAdvanceDecision.Finished(),
            ListenAdvancePolicy.Decide(10, 10, true, null, 0));
    }

    [Fact]
    public void Finishes_when_skip_would_pass_end()
    {
        Assert.Equal(
            new ListenAdvanceDecision.Finished(),
            ListenAdvancePolicy.Decide(9, 10, false, "summary_not_ready", 0));
    }
}
