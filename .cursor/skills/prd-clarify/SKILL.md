---
name: prd-clarify
description: >-
  Pause and clarify when a user request adds, changes, or removes product
  requirements relative to docs/PRD.md. Present original PRD text, current
  implementation, and the new request; wait for confirmation; then update the
  PRD before coding. Use when the user asks for a new feature, a change to
  existing product behavior, dropping a capability, something listed as out of
  scope / v1.1+, or when the request conflicts with the PRD constitution.
---

# PRD 需求澄清

产品真源是 `docs/PRD.md`。用户意图相对 PRD 是**新增 / 修改 / 删除**时：先整理对照、要求澄清；确认后再改 PRD，然后才实现。未确认前不改代码、不改 PRD、不「先做一版再说」。

## 何时必须停

对照 `docs/PRD.md`（故事 §2、IA §3、章程 §1、功能 §5、非功能 §7、不做 §9、开放项 §12）。命中即触发：

1. **新增需求**：PRD 未写，或写在 §9 明确不做 / 更晚版本（v1.1+）
2. **修改需求**：要改已锁定的故事（B1–B12、N1–N4）、§3、§5、§1、§7
3. **删除需求**：要拿掉 PRD 已有能力或验收项

**章程冲突单独标出**：新要求若动到章程 0（永不卡住用户）或 `.cursor/rules/never-freeze-ui.mdc`，澄清里必须单列；默认不当成「顺手改 PRD」。

## 何时不停

按现有 PRD 直接做：

- 修 bug / 对齐 PRD 的实现缺口（实现与 PRD 不一致 → 修实现，不改 PRD）
- 纯实现细节（拆函数、测试、重构），不改变用户可见产品行为
- 用户明确说「按 PRD 做」或只问现状

## 对话里怎么做

1. **对照**：读相关 PRD 节；架构/选型相关再读 `docs/TDD.md`。
2. **摸实现**：只读定位当前行为（入口、关键类型/API）。写清与 PRD：已对齐 / 部分实现 / 未做。不开始改。
3. **展示并澄清**：用户可见回复必须用下面三个标题（原文，不改写），再用 AskQuestion（或 1–2 个关键问题）锁范围：类型、v1.0 vs 以后、边界/不做、是否动章程。
4. **停住**：等用户确认。
5. **确认后**：先改文档，再实现。

### 原需求 / 现在的实现 / 新的需求

```markdown
## 需求差异（需确认后再改 PRD / 代码）

**类型**：新增 | 修改 | 删除
**PRD 锚点**：docs/PRD.md §… / 故事 B… 或 N…
**章程冲突**：无 | 有（写哪条）

### 原需求
- PRD 怎么写的（要点，可引用节号）

### 现在的实现
- 代码位置与实际行为
- 与 PRD：已对齐 / 部分实现 / 未做

### 新的需求
- 根据这次用户原话归纳（不自行加戏）

### 请确认
- 是否按「新的需求」改 v1.0 PRD？
- 范围边界与明确不做
- 若动章程 / §9：是否接受把该项移入 v1.0
```

## 确认后改哪些文档

最小范围，不扩写无关章节：

| 变了什么 | 改哪里 |
|----------|--------|
| 产品行为 / 故事 / 验收 | `docs/PRD.md`（对应故事、§5、§8 MVP；必要时 §9） |
| 架构 / 数据 / 技术选型 | 另改 `docs/TDD.md` |
| 用户故事 ID 或验收映射 | 另改 `docs/testing.md` 的故事↔E2E 表 |
| 章程 | 另改 `.cursor/rules/*.mdc`（如 `never-freeze-ui.mdc`） |

改完 PRD 再写代码。不要改 README；不要建需求工单库。
