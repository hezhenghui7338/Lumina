# Bad Case 目录

对话中确认过的坑必须落盘，发布前必须覆盖。流程见项目 skill [`.cursor/skills/badcase/SKILL.md`](../../.cursor/skills/badcase/SKILL.md) 与规则 [`.cursor/rules/collect-badcases.mdc`](../../.cursor/rules/collect-badcases.mdc)。

| 文件 | 用途 |
|------|------|
| `draft.jsonl` | 未升格。开发中可有；**release 必须为空** |
| `catalog.jsonl` | 正式集：`covered` / `rule` / `wontfix` |

## 字段

一行一条 JSON。必填：`id` `title` `symptom` `root_cause` `source` `status` `layer` `repro` `dedupe_key`。

- `id`：`bc-YYYYMMDD-slug`；draft 可用 `bc-draft-…`
- `source`：`chat:<uuid>` / `dogfood` / `pr`
- `status`：`draft` \| `covered` \| `rule` \| `wontfix`
- `layer`：`pytest` \| `swift` \| `windows` \| `rule`
- `test`：`path` 或 `path::symbol`，字符串或数组；`draft` / `wontfix` 可空
- `rule`：可选，`.cursor/rules/` 下文件名
- `repro`：最短复现
- `dedupe_key`：短英文 slug；写入前对两份 jsonl 去重

## 发布检查

```bash
python3 scripts/check-badcases.py
```

`scripts/run-release-tests.sh` 会先跑此检查，再跑 mock pytest。
