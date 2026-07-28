# 深聊测试 Fixture

## 拒答 Corpus

| 文件 | 用途 |
|------|------|
| `refusal_corpus.jsonl` | 正式集（≥20 条，`reviewed: true`） |
| `refusal_corpus.draft.jsonl` | 草稿，待产品审阅 |

**共建指南**：[docs/testing/refusal-corpus.md](../../../docs/testing/refusal-corpus.md)

## JSONL 一行一条

```json
{"id":"ref-001","book_fixture":"sample_classical.txt","segment_index":2,"segment_scope":"segment","question":"…","expected":"refuse","rationale":"…","author":"product","reviewed":false}
```

`expected`: `refuse` | `cite` | `web` | `cite_and_web`
