---
name: badcase
description: >-
  Harvest, dedupe, and promote conversation bad cases into tests/badcases,
  then gate releases so previously fixed failures cannot silently return.
  Use in every Lumina coding session when the user corrects the agent, reports
  a regression, says a fix came back, a test exposes a real invariant, or when
  preparing a release / just release / build-release.
---

# Bad Case 采集与发布回归

对话即采集。目录是真源；测试/规则是锁。发布跑 `scripts/check-badcases.py`，draft 未清空则失败。

## 何时必须记

- 用户纠错，或说「不对 / 还是 / 又坏了 / 之前修过」
- 已确认的产品 bug、回归、JSON/API 契约破裂
- 测试失败暴露的真实不变量（不是 flaky 误杀）
- agent 改完引入的倒退

## 何时不记

- 同一回合内 agent 自己改掉的笔误
- 纯风格偏好、一次性探索
- 尚未确认的猜测

## 文件

| 文件 | 用途 |
|------|------|
| `tests/badcases/draft.jsonl` | 本会话未升格；开发中可有；**禁止带进 release** |
| `tests/badcases/catalog.jsonl` | 正式集：`covered` / `rule` / `wontfix` |
| `scripts/check-badcases.py` | 发布完整性检查 |

写入前用 `rg` 对 `catalog.jsonl` + `draft.jsonl` 搜 `dedupe_key` 与 `title`。命中则更新那一行，不另开条目。

## Schema（一行一条 JSON）

必填：`id` `title` `symptom` `root_cause` `source` `status` `layer` `repro` `dedupe_key`

| 字段 | 说明 |
|------|------|
| `id` | 稳定 id：`bc-YYYYMMDD-slug`。draft 可用 `bc-draft-…`，升格时改稳定 id |
| `source` | `chat:<uuid>`（本机会话）或 `dogfood` / `pr` |
| `status` | `draft` \| `covered` \| `rule` \| `wontfix` |
| `layer` | `pytest` \| `swift` \| `windows` \| `rule` |
| `test` | `path` 或 `path::symbol`；可字符串或字符串数组。`draft` / `wontfix` 可空 |
| `rule` | 可选。`.cursor/rules/` 下文件名，如 `never-freeze-ui.mdc` |
| `repro` | 最短复现（命令或操作） |
| `dedupe_key` | 短英文 slug |

## 对话里怎么做

1. **发现即写**：追加 `draft.jsonl` 一行，`status: draft`。不打断用户问要不要记。
2. **本任务在修这个坑**：同变更写最小回归测试 → 将该行挪到 `catalog.jsonl`，`status: covered`，填 `test`。从 draft 删掉。
3. **流程不变量**（如永不卡 UI）：落 `.cursor/rules/*.mdc`，catalog `status: rule`，`layer: rule`，`test` 为规则文件名。
4. **明确不锁**：catalog `status: wontfix`，写清 `root_cause`。
5. **收尾**：若本对话写过 draft，用一句话列出 id（不贴大段 JSON）。
6. **发布**：先 `python3 scripts/check-badcases.py`。失败则升格、补测试或标 `wontfix`，再打包。

Python 用例放现有 `packages/lumina-core/tests/unit` 或 `tests/e2e`，不要新建 `@pytest.mark.badcase`。Swift / Windows 在 catalog 里做指针；v1 release 脚本只跑 pytest，Swift 存在性由 check 脚本核对，执行仍走 `just test-macos` / CI。

## 检查失败条件

`scripts/check-badcases.py` 非零退出当：

- `draft.jsonl` 有非空 JSON 行
- `catalog.jsonl` 出现 `status: draft`（draft 只属于 draft 文件）
- `covered` 的 `test` 路径不存在，或代码文件里找不到 `::symbol`
- `status: rule` 但 `.cursor/rules/` 中对应文件不存在
- 缺必填字段，或 `id` / `dedupe_key` 重复

## 初始种子（勿再复制）

已在 catalog 的：`bc-favorite-json-bool`、`bc-never-freeze-slim-list`、`bc-refusal-corpus`。
