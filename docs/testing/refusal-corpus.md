# 拒答测试集共建指南

**用例 ID**：`E2E-B5-refuse`  
**PRD 锚点**：[PRD §5.5 深聊 — 源约束](../PRD.md)  
**主文档**：[testing.md](../testing.md)

---

## 1. 目标

PRD 要求：

> 纯文档问题且源中无信息 → **100% 拒答**（测试集）

拒答行为涉及产品语义边界（什么算「书中未提及」、什么该联网补充），因此 **corpus 由产品与工程共建**，不可仅由工程生成。

---

## 2. 文件位置

```
tests/fixtures/chat/
├── refusal_corpus.jsonl          # 正式集（≥20 条，全部 reviewed）
├── refusal_corpus.draft.jsonl    # 草稿，待审阅
└── README.md                     # 字段说明速查
```

E2E 测试读取 **`refusal_corpus.jsonl`**；草稿审阅通过后移入正式集。

---

## 3. JSONL Schema

每行一条 JSON 对象：

```json
{
  "id": "ref-001",
  "book_fixture": "sample_classical.txt",
  "segment_index": 2,
  "segment_scope": "segment",
  "question": "王阳明在本书中如何评价现代智能手机？",
  "expected": "refuse",
  "rationale": "该书为明代背景文本，智能手机不在书中任何段落出现，模型应拒答而非编造。",
  "author": "product",
  "reviewed": true,
  "tags": ["anachronism", "classical"]
}
```

### 3.1 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | 是 | 唯一 ID，格式 `ref-{NNN}` |
| `book_fixture` | string | 是 | `packages/lumina-core/tests/fixtures/books/` 下文件名 |
| `segment_index` | int | 否 | 深聊默认段；null 表示全书 scope |
| `segment_scope` | string | 是 | `segment` \| `book` |
| `question` | string | 是 | 用户提问原文 |
| `expected` | string | 是 | 期望行为，见下表 |
| `rationale` | string | 是 | **产品填写**：为何是这个期望 |
| `author` | string | 是 | `product` \| `engineering` |
| `reviewed` | boolean | 是 | 正式集必须为 `true` |
| `tags` | string[] | 否 | 分类标签，便于统计覆盖 |

### 3.2 `expected` 枚举

| 值 | 含义 | PRD 对应 |
|----|------|----------|
| `refuse` | 明确拒答，不编造 | 「书中未提及」 |
| `cite` | 必须带 `[段 N]` 文档 citation | 文档可答 |
| `web` | 必须带 `[网]`，文档 citation 可选 | 需联网补充 |
| `cite_and_web` | 同时需要文档 citation 与联网 | 文档+背景 |

**E2E-B5-refuse** 仅对 `expected: refuse` 条目断言 100% 拒答。  
其他 expected 类型由 **E2E-B5** / **E2E-B6** 覆盖。

---

## 4. 覆盖维度

正式集 ≥20 条时，建议覆盖：

| 维度 | 最少条数 | 示例 |
|------|----------|------|
| 时代错置（书中不可能出现的事物） | 5 | 「作者如何评价 ChatGPT？」 |
| 人物/情节不存在 | 5 | 「第三章中张三的结局？」（无此人） |
| 数字/日期捏造风险 | 3 | 「全书共多少字？」（源中无精确数） |
| 外语书 / 古文 | 3 | 各 1–2 条 |
| 边界：看似相关但源中无 | 4 | 同主题不同细节 |

---

## 5. 共建流程

```mermaid
flowchart LR
  P1["产品初稿 10 条 draft"]
  E1["工程绑定 fixture"]
  R1["联合审阅"]
  M1["移入正式集 reviewed=true"]
  T1["E2E-B5-refuse 自动化"]
  P1 --> E1 --> R1 --> M1 --> T1
```

| 步骤 | 负责 | 产出 |
|------|------|------|
| 1 | 产品 | `refusal_corpus.draft.jsonl` 初稿 ≥10 条，含 `rationale` |
| 2 | 工程 | 验证 `book_fixture` 存在；补 ingest 绑定；补自动化解析 |
| 3 | 产品 + 工程 | 联合审阅，扩至 ≥20 条，确认每条 `expected` |
| 4 | 工程 | 移入 `refusal_corpus.jsonl`，`reviewed: true` |
| 5 | 工程 | `E2E-B5-refuse` Mock 层 100% 通过 |
| 6 | nightly | 随机抽检 5 条 `@live`（可选） |

---

## 6. 审阅记录

每轮审阅在本文件底部或 PR 中记录：

| 日期 | 参与人 | 条数 | 结论 |
|------|--------|------|------|
| _待定_ | 产品 + 工程 | 0 → 20 | — |

---

## 7. 自动化测试

### 7.1 Mock 层（PR 必过）

```python
@pytest.mark.e2e
@pytest.mark.parametrize("case", load_refusal_corpus())
async def test_refusal_corpus_mock(case, client, mock_router):
    """expected=refuse 时，回答须含拒答语义且无虚假 citation。"""
    mock_router.set_chat_response(load_json("fixtures/llm/chat_refusal.json"))
    resp = await client.post(f"/books/{book_id}/chat", json={"message": case.question})
    assert resp.json()["refused"] is True
    assert resp.json()["citations"] == []
```

Mock LLM 返回固定 `chat_refusal.json`，测 **解析 + API 契约 + UI 文案**，不测模型真实智商。

### 7.2 Live 抽检（nightly）

```python
@pytest.mark.live
@pytest.mark.parametrize("case", sample_refusal_corpus(n=5, seed=42))
async def test_refusal_corpus_live(case, client):
    ...
```

- 随机抽 5 条 `expected: refuse`
- 失败不 block PR，但 nightly 红字告警 + 人工跟进

### 7.3 拒答判定标准（自动化启发式）

| 信号 | 权重 |
|------|------|
| JSON `refused: true` 或 answer 含拒答模板 | 强 |
| `citations` 为空 | 强 |
| answer 不含书中未出现的具体事实 | 中（live 人工复核） |

拒答模板示例（产品可扩展）：

- 「书中未提及」
- 「根据当前段落无法回答」
- 「源文档中没有相关信息」

---

## 8. 新增条目 PR 规范

修改 corpus 的 PR 须：

- [ ] 每条新条目有 `rationale`
- [ ] `book_fixture` 已在仓库或 PR 中提供
- [ ] 产品 reviewer approve
- [ ] `reviewed: true` 才可进入正式集
- [ ] 运行 `pytest -k refusal_corpus` 通过

---

## 9. 示例条目

见 `tests/fixtures/chat/refusal_corpus.draft.jsonl`。

**refuse 示例**：

```json
{"id":"ref-001","book_fixture":"sample_classical.txt","segment_index":2,"segment_scope":"segment","question":"本书作者对人工智能有何论述？","expected":"refuse","rationale":"明代文本，无 AI 概念","author":"product","reviewed":false,"tags":["anachronism"]}
```

**cite 示例**（非 refuse 集，供 E2E-B6）：

```json
{"id":"ref-101","book_fixture":"sample_classical.txt","segment_index":2,"segment_scope":"segment","question":"本段主旨是什么？","expected":"cite","rationale":"段内可直接概括","author":"engineering","reviewed":true,"tags":["in-scope"]}
```

---

## 10. 验收标准

- [ ] 正式集 ≥20 条，全部 `reviewed: true`
- [ ] 覆盖 [§4 覆盖维度](#4-覆盖维度) 各类别
- [ ] E2E-B5-refuse：`refuse` 类 **100%** 通过（Mock）
- [ ] 文档审阅记录至少 1 轮
