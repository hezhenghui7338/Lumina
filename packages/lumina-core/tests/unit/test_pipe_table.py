"""Unit tests for pipe/GFM table formatting."""

from lumina_core.ingest.pipe_table import format_pipe_table


def test_format_pipe_table_wraps_and_escapes():
    out = format_pipe_table([["甲", "a|b"], ["乙", "二"]], header=True)
    assert out.startswith("\n\n")
    assert out.endswith("\n\n")
    assert "| 甲 | a\\|b |" in out
    assert "| --- | --- |" in out
    assert "| 乙 | 二 |" in out


def test_format_pipe_table_skips_empty():
    assert format_pipe_table([["", ""], []]) == ""
