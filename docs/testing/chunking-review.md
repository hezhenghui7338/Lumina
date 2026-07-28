# 长文本切割 Live 验收指南

**用例 ID**：`E2E-CHUNK-LIVE`  
**PRD 锚点**：[PRD §5.3 智能分段与摘要](../PRD.md)  
**主文档**：[testing.md](../testing.md)

---

## 1. 为何单独 Live

长文本切割是 Lumina 的核心体验。Mock LLM 无法验证：

- 段边界是否落在章节/语义自然断点
- 摘要是否覆盖本段主旨（而非邻段内容）
- 段列表 `label`（≤20 字）是否可用于导航

因此 **切割 + 真实 Ollama 摘要段 0/1** 是测试体系中**唯一必须在 PR/本地走真实 Ollama 的路径**；深聊、翻译、prefetch 其余段仍 Mock。

---

## 2. 测试流程

```
fixture 长文本
    → ingest（真实）
    → chunker（真实，不 Mock）
    → Ollama summarize 段 0
    → Ollama summarize 段 1
    → 结构化断言（自动）
    → chunking_report.md（人工审阅）
```

**不测**：段 2+ prefetch、翻译、深聊、联网。

---

## 3. Fixture 规格

| 文件 | 场景 | 规模 | 路径 |
|------|------|------|------|
| `chunk_long_novel.txt` | 网文式：多章、段落边界模糊 | ~80k–150k 字 | `packages/lumina-core/tests/fixtures/books/` |
| `chunk_classical.txt` | 古文：章节结构清晰 | ~30k–50k 字 | 同上 |
| `chunk_epub_chapters.epub`（可选） | EPUB 章节结构保留 | 中等 | 同上 |

**Fixture 选取原则**：

- 使用无版权风险或已获授权的文本
- 长文 fixture 应包含至少 2 个明确章节/篇目，便于检验章节边界
- 网文 fixture 应包含「超长单章」场景，迫使 chunker 按字数二次切分

---

## 4. 自动化断言

### 4.1 必须通过（block CI）

| # | 断言 | 说明 |
|---|------|------|
| A1 | 段数 ≥ 2 | 长文 fixture 必为多段 |
| A2 | 段 0/1 `summary_status == ready` | Ollama 摘要成功 |
| A3 | 每段 `raw_text` 长度 ∈ [2400, 9600] | 目标 3000–8000 字，±20% |
| A4 | 段 0 与段 1 字符 offset **无重叠** | `end_0 <= start_1` |
| A5 | 摘要 JSON schema 合法 | 见下表 |
| A6 | `label` 长度 ≤ 20 字（Unicode 字符数） | PRD §5.3 |
| A7 | `anchor` 含段序号 | 如 `段 1` |

**摘要 JSON schema**（TDD §4.3）：

| 字段 | 约束 |
|------|------|
| `sentences` | 数组，长度 1–3 |
| `bullets` | 数组，长度 3–7 |
| `label` | 字符串，≤20 字 |
| `anchor` | 字符串，含章节/段/页码信息 |

### 4.2 软断言（人工审阅，不 block CI）

| # | 检查项 |
|---|--------|
| S1 | 段 0/1 边界是否在语义/章节自然断点 |
| S2 | 摘要是否准确概括本段，无邻段串台 |
| S3 | `label` 是否可读、能代表段内容 |
| S4 | 古文 fixture：摘要/label 是否尊重原文语境 |

---

## 5. 审阅报告

测试运行后生成：

```
tests/output/chunking_report_{timestamp}.md
```

（目录已 gitignore，审阅结论粘贴到 PR 或存档 wiki。）

### 5.1 报告模板

```markdown
# Chunking Live Report

- **Fixture**: chunk_long_novel.txt
- **Date**: 2026-07-28
- **Model**: qwen3.5:4b
- **Ollama URL**: http://localhost:11434
- **Total segments**: 42
- **Duration**: 87.3s

## Segment 0

- **Chars**: 6124
- **Label**: 「引子：主角出身寒门」
- **Anchor**: §第一章 · 段 1 · p.1-5
- **Preview** (first 200 chars): …
- **Summary sentences**:
  1. …
  2. …
  3. …
- **Bullets**: …

## Segment 1

- **Chars**: 5891
- **Label**: 「科举之路起笔」
- …

## Boundary check

- Segment 0 ends at char offset: 6124
- Segment 1 starts at char offset: 6124
- Overlap: none

## Review checklist

- [ ] S1 段 0/1 边界合理
- [ ] S2 摘要准确、无串台
- [ ] S3 label 可用于段列表导航
- [ ] S4 古文/网文特殊场景 OK（如适用）

## Sign-off

- **Reviewer**: @name
- **Result**: PASS / FAIL / PASS with notes
- **Notes**: …
```

---

## 6. 运行方式

### 6.1 前置

```bash
ollama serve
ollama pull qwen3.5:4b

# 可选：指定模型
export LUMINA_SUMMARIZE_MODEL=qwen3.5:4b
export OLLAMA_BASE_URL=http://localhost:11434
```

### 6.2 执行

```bash
# 推荐
just test-chunking

# 或直接 pytest
cd packages/lumina-core
pytest tests/live -m live_chunk -v -s

# 生成报告并打开
just test-chunking-report
```

### 6.3 pytest 标记

```python
@pytest.mark.live_chunk
@pytest.mark.skipif(not ollama_available(), reason="Ollama required")
async def test_chunk_long_novel_segment_0_and_1(...):
    ...
```

**注意**：`live_chunk` 与 `live` 分开标记，避免 nightly 全量 live 与切割验收混淆。

---

## 7. CI 触发

| 触发条件 | Workflow |
|----------|----------|
| 每 PR 改 `chunker/**` 或 `summarize/**` | `test-chunking.yml` |
| manual dispatch | `test-chunking.yml` |
| nightly | 全量 fixture |

CI 须：

1. 启动 Ollama 服务（或连接 self-hosted runner 上的 Ollama）
2. 预 pull `qwen3.5:4b`（或 `0.8b` 降级，见下）
3. 上传 `chunking_report_*.md` 为 artifact

**CI 模型降级**：内存 <10GB 的 runner 可用 `qwen3.5:0.8b`，但 PR sign-off 仍以 4b 本地结果为准。

---

## 8. 何时必须跑

| 变更类型 | 必须 `@live_chunk` |
|----------|-------------------|
| `chunker/` 算法、参数 | 是 |
| `summarize/` prompt、JSON schema | 是 |
| ingest 文本提取影响分段输入 | 是 |
| SwiftUI 段列表样式 | 否（Snapshot 即可） |
| 深聊 / 翻译 / 联网 | 否 |

---

## 9. Wave 1 Gate

Dogfood 阶段合并前：

- [ ] `chunk_long_novel.txt` live 通过 + 报告 sign-off
- [ ] `chunk_classical.txt` live 通过 + 报告 sign-off
- [ ] 两份报告已由至少 1 名工程 + 1 名产品/设计审阅

---

## 10. 常见问题

**Q: 摘要内容每次不同，如何 CI？**  
A: 结构化断言（schema、段长、offset）是 hard gate；摘要语义由人工 report sign-off，不 block 自动 CI。

**Q: Ollama 未启动？**  
A: 本地 `@live_chunk` skip；改 chunker 的 PR 须等 CI `test-chunking.yml` 绿。

**Q: 段长超出 ±20%？**  
A: 检查 chunker 参数或 fixture 是否含异常超长段落；可调 `LUMINA_CHUNK_TARGET_CHARS` 后重跑并更新基线说明。
