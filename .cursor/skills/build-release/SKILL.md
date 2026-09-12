---
name: build-release
description: >-
  Run Lumina release packaging via ./scripts/build-release.sh or just release,
  and on failure auto-diagnose and minimally fix in the same Agent chat for at
  most 3 rounds before reporting the full error to the user. Use when the user
  asks to build-release, run build-release.sh, just release, package a release,
  or when a release build fails in Agent.
---

# build-release 失败自修

在 **Agent 对话**内跑发布构建。失败则同一对话最小修复并重跑，最多 **3 轮**；仍失败则完整报错给用户。系统终端直接跑脚本不触发本 skill。

配套 hook（硬顶）：`.cursor/hooks.json` 的 `stop` 使用 `loop_limit: 3`；状态文件 `.cursor/hooks/state/build-release.json`。

## 何时用

- 用户要求 `./scripts/build-release.sh`、`just release`、release 打包 / 发布构建
- 上述命令在本对话中已失败，需续修或收尾上报

## 流程

1. 读本 skill（及失败若涉 badcase 门禁则读 `badcase` skill）。
2. 执行 `./scripts/build-release.sh`（或用户指定的等价命令，如带 `LUMINA_VERSION=…`）。
3. **成功**：结束；勿再开修复轮。
4. **失败**：进入修复轮（见下）。遇到「禁止自动修」项 → 直接按模板上报，不消耗无意义的修轮。
5. 每轮：诊断日志 → 最小改动 → **再跑同一条构建命令**。
6. 满 3 轮仍失败，或 hook 标 `exhausted`：只上报，不再改、不再跑。

## 一轮定义

一次「看到失败 → 改代码/配置 → 再次执行 build-release」= **1 轮**。同轮内可读日志、搜代码、跑窄测，不算多轮。

## 优先自动修

- pytest / `scripts/run-release-tests.sh` 失败（修测试或实现，不删门禁）
- `check-badcases` 失败 → 按 **badcase** skill 升格 / 补测 / `wontfix`，禁止清空 draft 蒙混
- 可安装且不改产品行为的缺依赖
- 明显脚本 / 路径笔误
- `sync-release-identity` 相关失败 → 遵循 `.cursor/rules/sync-release-identity.mdc`，不手写分叉版本号

## 禁止自动修（直接上报）

- 需要密钥、公证、签名账号
- Xcode 未装或仅有 CLT、系统级环境缺失
- 放宽体积上限、跳过 / 削弱测试或 `check-badcases`
- 删 draft 不升格；改 PRD；未请求的 commit / force push
- 任何会违反 never-freeze-ui 章程的「为过构建而改产品行为」

## 失败报告模板

向用户报告时用以下结构（简明）：

```markdown
## build-release 失败（已停止自动修复）

- **阶段**: tests | pyinstaller | prune/ocr-smoke | xcode | codesign | dmg | other
- **命令**: …
- **轮次**: n/3
- **日志摘录**:
  ```
  （stderr/stdout 尾部，适度截断）
  ```
- **已尝试**:
  1. …
  2. …
- **建议人工下一步**: …
```

## 约束

- 不放宽 release 门禁；不改 `build-release.sh` 来跳过检查。
- 修复不得引入阻塞 UI 的写法（见 never-freeze-ui）。
- 默认同一对话续修；不要为常规失败去开 Task 子 Agent。
