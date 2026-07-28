#!/usr/bin/env python3
"""Generate synthetic long-text fixtures for @live_chunk tests."""
from __future__ import annotations
from pathlib import Path

BOOKS_DIR = Path(__file__).resolve().parents[1] / "packages" / "lumina-core" / "tests" / "fixtures" / "books"

def _paragraph(seed: int) -> str:
    topics = [
        "主角在集市听闻新政，心中波澜起伏",
        "友人论及科举变革，各执一词难以相让",
        "夜读时见窗外月色，想起故乡旧景",
        "路遇商队述说边关战事，民生多艰",
        "师友来信论学，提及义理与考据之争",
    ]
    t = topics[seed % len(topics)]
    return f"　　{t}。彼时风气渐开，士子多议论天下大事。或引经据典，或据实直陈，言辞间不乏激越之意。（段落 {seed + 1}）\n\n"

def generate_long_novel(target_chars: int = 100_000) -> str:
    parts = ["长篇网文测试样例 — 合成文本，无版权风险\n\n"]
    chapter = 1
    while sum(len(p) for p in parts) < target_chars:
        parts.append(f"第{chapter}章 情节推进\n\n")
        para_in_chapter = 0
        while para_in_chapter < 80 and sum(len(p) for p in parts) < target_chars:
            parts.append(_paragraph(chapter * 100 + para_in_chapter))
            para_in_chapter += 1
        chapter += 1
    return "".join(parts)[:target_chars]

def generate_classical(target_chars: int = 40_000) -> str:
    parts = ["古文测试样例 — 合成章节文本\n\n"]
    chapters = ["第一章 学而", "第二章 为政", "第三章 八佾", "第四章 里仁", "第五章 公冶长"]
    idx = ch_i = 0
    while sum(len(p) for p in parts) < target_chars:
        if idx % 25 == 0:
            parts.append(f"{chapters[ch_i % len(chapters)]}\n\n")
            ch_i += 1
        parts.append(f"　　子曰：学而不厌，诲人不倦，何有于我哉。（条目 {idx + 1}）\n\n")
        parts.append(f"　　弟子问曰：何谓仁？子曰：克己复礼为仁。（条目 {idx + 1} 续）\n\n")
        idx += 1
    return "".join(parts)[:target_chars]

def main() -> None:
    BOOKS_DIR.mkdir(parents=True, exist_ok=True)
    novel, classical = generate_long_novel(), generate_classical()
    (BOOKS_DIR / "chunk_long_novel.txt").write_text(novel, encoding="utf-8")
    (BOOKS_DIR / "chunk_classical.txt").write_text(classical, encoding="utf-8")
    print(f"Wrote chunk_long_novel.txt ({len(novel):,} chars)")
    print(f"Wrote chunk_classical.txt ({len(classical):,} chars)")

if __name__ == "__main__":
    main()
