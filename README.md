<p align="center">
  <img src="docs/assets/lumina-logo.png" alt="Lumina — Local AI Reading Companion" width="480">
</p>

<p align="center">
  <strong>Local AI Reading Companion · AI 伴读</strong><br>
  让阅读速度提升 5 倍，而理解深度提升 10 倍。
</p>

<p align="center">
  macOS 14+ · MIT · <a href="https://github.com/hezhenghui7338/Lumina/releases/latest">Latest Release</a>
</p>

<p align="center">
  <a href="#功能特性">功能特性</a> ·
  <a href="#最近更新">最近更新</a> ·
  <a href="#普通用户--下载即用">下载安装</a> ·
  <a href="#开发者">开发者</a>
</p>

---

## 功能特性

- **本地优先** — 默认 Ollama 本机跑通导入 → 摘要 → 深聊，书与笔记数据不出机
- **多格式书库** — 支持 PDF / EPUB / MOBI / TXT，智能分段 + 三句摘要
- **沉浸式阅读** — 贴边段列表 / 笔记 / 深聊，摘要 ↔ 原文一键切换
- **深度理解** — 古文、外文自动翻译；段级 citation 可溯源；可选联网增强
- **读书记忆** — 跨书笔记 + **⌘K** 全局搜索，随时找回读过的内容
- **资讯** — RSS 同步、结构化简报与精读深聊
- **可扩展** — 可选 OpenAI / OpenRouter / Cursor 兼容 API；整书摘要导出 Markdown

---

## 最近更新

### v0.4 — 大文件阅读与导入更流畅

- 段列表**按需加载**摘要，不必等全书生成即可开始阅读
- 后台解析 + **批量 SSE 刷新**，导入与摘要不卡 UI
- 滚动与预取**防抖**、Equatable 渲染，千万字长书更顺滑
- 后端 SQLite 写锁与**瘦 API**，事件流不被阻塞

### v0.3 — 本地 Ollama 摘要更稳更好

- 针对小模型精简 prompt 与解析，**重试 + 进度指标**
- **任务管理** UI：查看 / 取消进行中的导入与摘要
- **资源并发**可调（设置 → API 资源），配合 `OLLAMA_NUM_PARALLEL`
- Ops API 与可观测性增强

---

## 普通用户 · 下载即用

> 你**不需要**安装 Python、uv、Xcode 或任何命令行工具。下载安装包，拖进「应用程序」即可。

### 下载

| 平台 | 要求 | 下载 |
|------|------|------|
| macOS 14+（Apple Silicon / Intel） | 约 250 MB 安装包（安装后约 450 MB）+ 首次 AI 模型 ~3 GB | **[GitHub Releases 下载 DMG](https://github.com/hezhenghui7338/Lumina/releases/latest)** |

Release 页提供 **Lumina-0.3.0-macOS.dmg**（由 GitHub Actions 自动构建）。若尚未上传 DMG，见下方「维护者构建」。

### 安装（两步）

1. 打开下载的 **`.dmg`**，将 **Lumina** 拖入 **Applications（应用程序）** 文件夹  
2. 从启动台或应用程序文件夹打开 **Lumina**

### 首次打开：「无法验证 / 可能危害 Mac」

这是 **正常现象**。当前 Release 由 GitHub Actions 自动构建，尚未经过 Apple 付费开发者签名与公证，macOS 会对**任何**未公证的本机应用显示此提示，**不代表有病毒**。

任选一种方式即可打开（只需操作一次）：

**方法 1（推荐）**

1. 在「应用程序」里找到 **Lumina**
2. **按住 Control 键点击**（或右键）→ 选 **「打开」**
3. 弹窗中再点 **「打开」**

**方法 2**

1. 先双击 Lumina（会被拦截）
2. 打开 **系统设置 → 隐私与安全性**
3. 向下滚动，找到 **「已阻止使用 Lumina」** 或类似提示
4. 点 **「仍要打开」**

**方法 3（熟悉终端时）**

```bash
xattr -cr /Applications/Lumina.app
```

然后照常双击打开。

> 后续版本若加入 Apple 开发者签名与公证，此提示将不再出现。

### 首次使用

打开 App 后按屏幕引导操作即可：

1. **Lumina 引擎** — 自动启动，无需配置  
2. **本地 AI（Ollama）** — 一键打开 [ollama.com/download](https://ollama.com/download) 安装；安装后在 Ollama 里搜索并下载 **qwen3.5:4b**（约 3.4 GB，仅首次）  
3. **导入书籍** — 点「导入」，选择 PDF / EPUB / MOBI / TXT

> **说明**：Ollama 是免费的本机 AI 运行时（类似本地版 ChatGPT 引擎）。Lumina 已内置阅读引擎，Ollama 仅负责 AI 摘要与对话，数据不出本机。

### 日常使用

| 操作 | 方法 |
|------|------|
| 导入书 | 书库 → **导入** |
| 阅读 / 深聊 | 选中书籍 → 左侧段列表 + 段摘要；触左段列表、触右笔记、触底提问（工具栏亦可收起段列表） |
| 跨书笔记 | 书库 → **全部笔记** |
| 跨书搜索 | **⌘K** |
| 资讯 | 顶部 **资讯** Tab → **同步 RSS** |
| 导出摘要 | 阅读器 → **导出** |
| 任务管理 | **设置** Tab → 查看 / 取消进行中的导入与摘要 |
| 设置 | **设置** Tab（语言、联网 provider、深色模式） |

> **说明**：**Cursor** 预设资源走 OpenAI 兼容 HTTP 路径（`POST /v1/chat/completions`），需在设置中配置代理 Base URL 与 API Key（Cursor 官方暂无原生 chat/completions endpoint）。默认亦支持 Ollama、OpenAI、OpenRouter 等。

### 数据在哪

全部在本机，路径：

```
~/Library/Application Support/Lumina/
```

### 常见问题

**提示「Apple 无法验证 Lumina…」？**  
见上方 [首次打开](#首次打开无法验证--可能危害-mac) 三种方法；推荐右键 → **打开**。

**打不开 / 提示损坏？**  
系统设置 → 隐私与安全性 → 仍要打开；或右键 Lumina → 打开。

**导入失败？**  
确认 Ollama 已安装且在运行（菜单栏有 Llama 图标），并已下载 `qwen3.5:4b` 模型。

**内存较小？**  
在 Ollama 中改用 `qwen3.5:2b` 或 `qwen3.5:0.8b`，并在 Lumina **设置** 中调整（若已配置模型）。

**升级后云端 API Key 失效？**  
旧版曾把密钥存在 macOS 钥匙串；新版改由本机 `~/Library/Application Support/Lumina/secrets.json` 保存。若升级后联网或云端模型不可用，请在 **设置** 中重新输入 API Key 并保存一次。

**第一段摘要较慢？**  
首次把模型载入内存需 30 秒～2 分钟，属正常现象。

**想加快整书摘要？**  
在 **设置 → API 资源** 中编辑 Ollama 资源，将「并发」调到 2–3（默认 2）。同时为本机 Ollama 设置 `OLLAMA_NUM_PARALLEL`（建议与并发一致），例如 Homebrew：

```bash
# ~/Library/LaunchAgents/homebrew.mxcl.ollama.plist 的 EnvironmentVariables 中加入
# OLLAMA_NUM_PARALLEL=2
# 然后重启 ollama serve
```

内存吃紧或单段延迟变差时调回 1。

---

## 开发者

面向贡献者与从源码构建的同学。普通用户请只看上一节。

### 环境

- macOS 14+
- [Xcode 15+](https://developer.apple.com/xcode/)
- [uv](https://docs.astral.sh/uv/)（Python **3.11+**）
- [Ollama](https://ollama.com) + `qwen3.5:4b`

### 本地开发

```bash
git clone <repo> && cd Lumina

# 安装 Python 依赖
just install

# 终端 A：Sidecar
just core

# Xcode：打开 apps/macos/Lumina.xcodeproj → ⌘R
# 或在 Scheme 中设置 LUMINA_CORE_DIR=$PWD/packages/lumina-core
```

### 测试

```bash
just test          # 单元 + e2e（Mock LLM）
just test-live     # 完整长文 live_chunk（需本机 Ollama，人工审阅用）
just test-release  # 发布门禁：纯 mock 并行（~20s，与 PR 等价）
```

### 打开发布包（给普通用户）

**推荐：GitHub Actions（无需本机 Xcode）**

1. 打开仓库 **Actions → Release → Run workflow**
2. 输入版本号（如 `0.3.0`）运行
3. 在 Artifacts 或 tag Release 中下载 DMG

**本机构建（需与 macOS 版本匹配的 Xcode）**

macOS 15 用户：**不要**从 App Store 装最新 Xcode（可能要求 macOS 26+）。请从 [Apple 开发者下载页](https://developer.apple.com/download/all/) 安装 **Xcode 16.x**（支持 macOS 15）。

```bash
./scripts/build-release.sh
# 会先跑 just test-release 等价测试，通过后才打包
# 产出：dist/Lumina-0.3.0-macOS.dmg 与 .zip
```

打 tag 推送后会自动构建并上传到 Release：

```bash
git tag v0.3.0 && git push origin v0.3.0
```

### 文档

- [PRD](docs/PRD.md) · [TDD](docs/TDD.md)
- [Sidecar API](packages/lumina-core/README.md)

---

## 许可证

MIT
