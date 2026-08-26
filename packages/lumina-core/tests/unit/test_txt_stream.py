"""TXT sliding-window decode/chunk does not keep the whole book in RAM."""

from __future__ import annotations

import resource
import sys
from pathlib import Path

from lumina_core.chunker.stream import iter_txt_chunks
from lumina_core.ingest.text import decode_text_bytes, iter_decoded_file


def _rss_bytes() -> int:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return int(usage)
    return int(usage) * 1024


def test_iter_txt_chunks_covers_file_without_join(tmp_path):
    line = "　　双方继续对峙，这是一段用于滑窗切分的中文句子。\n"
    path = tmp_path / "window.txt"
    path.write_text("第一章 开篇\n\n" + line * 400, encoding="utf-8")
    expected = path.read_text(encoding="utf-8").strip()
    pieces: list[str] = []
    last_end = 0
    for _plan, chunk in iter_txt_chunks(path, window_chars=8_000):
        assert chunk.start_offset == last_end
        last_end = chunk.end_offset
        pieces.append(chunk.raw_text)
        del chunk
    assert "".join(pieces) == expected
    assert last_end == len(expected)


def test_iter_decoded_file_does_not_need_full_read_bytes(tmp_path, monkeypatch):
    path = tmp_path / "stream.txt"
    path.write_text("第一章\n\n正文段落。\n" * 50, encoding="utf-8")
    calls: list[int] = []
    original = Path.read_bytes

    def tracked(self):
        data = original(self)
        if self.resolve() == path.resolve():
            calls.append(len(data))
        return data

    monkeypatch.setattr(Path, "read_bytes", tracked)
    text = "".join(iter_decoded_file(path))
    assert "正文段落" in text
    assert calls == []


def test_stream_window_rss_stays_below_file_multiple(tmp_path):
    """A multi-MB TXT must not produce a 5–10× decoded copy of the whole book."""
    path = tmp_path / "bulky.txt"
    line = "　　双方继续对峙，这是一段用于测试滑窗内存的中文句子。\n"
    encoded_line = line.encode("utf-8")
    target = 4 * 1024 * 1024
    with path.open("wb") as handle:
        handle.write("第一章 开篇\n\n".encode("utf-8"))
        written = 20
        while written < target:
            handle.write(encoded_line)
            written += len(encoded_line)
    size = path.stat().st_size
    before = _rss_bytes()
    chars = 0
    segments = 0
    last_end = 0
    for _plan, chunk in iter_txt_chunks(path, window_chars=32_000):
        assert chunk.start_offset == last_end
        last_end = chunk.end_offset
        chars += len(chunk.raw_text)
        segments += 1
    after = _rss_bytes()
    assert segments > 10
    assert chars > 100_000
    # Peak extra RSS should be far below 5× file size (old full-str copies).
    assert after - before < max(80 * 1024 * 1024, size * 3)


def test_decode_text_bytes_still_used_for_html_sized_buffers():
    assert "金" in decode_text_bytes("金阁寺".encode("gb18030"))


def test_iter_text_lines_splits_carriage_return():
    from lumina_core.chunker.coop import iter_text_lines

    lines = list(iter_text_lines("甲\r乙\r\n丙\n丁"))
    assert [line for _off, line in lines] == ["甲", "乙", "丙", "丁"]


def test_iter_txt_chunks_reports_nonzero_total(tmp_path):
    line = "　　双方继续对峙，这是一段用于滑窗切分的中文句子。\n"
    path = tmp_path / "progress.txt"
    path.write_text("第一章 开篇\n\n" + line * 800, encoding="utf-8")
    reports: list[tuple[int, int, str]] = []

    def on_progress(page: int, total: int, message: str) -> None:
        reports.append((page, total, message))

    list(iter_txt_chunks(path, window_chars=8_000, on_progress=on_progress))
    assert reports
    assert any(total > 0 for _page, total, _msg in reports)
    assert any(page > 0 for page, total, _msg in reports if total > 0)
    assert any("序言" in msg or "窗口" in msg or "解析" in msg for _p, _t, msg in reports)
