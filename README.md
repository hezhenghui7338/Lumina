<p align="center">
  <img src="docs/assets/lumina-logo.png" alt="Lumina — Local AI Reading Companion" width="480">
</p>

<p align="center">
  <strong>Local AI Reading Companion · AI 伴读</strong><br>
  让阅读速度提升 5 倍，而理解深度提升 10 倍。
</p>

<p align="center">
  macOS 14+ · Windows 10/11（P0） · MIT · <a href="https://github.com/hezhenghui7338/Lumina/releases/latest">Latest Release</a>
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
- **多格式书库** — 电子书 PDF / EPUB / MOBI / FB2，办公文档 DOCX / ODT / RTF，网页 HTML，以及 Markdown / TXT
- **语义分段** — 识别序言/章节角色，不从句中切断；可手动调界或整书重新分段
- **扫描 PDF OCR** — 默认本机 RapidOCR；可在设置中配置 OpenAI 兼容视觉 API，配置完整时云端优先
- **书架详览** — 智能集合（最近 / 摘要进度 / 阅读进度 / 分类 / 收藏）+ 网格或列表
- **沉浸式阅读** — 贴边段列表 / 笔记 / 深聊，摘要 ↔ 原文一键切换
- **深度理解** — 古文、外文自动翻译；段级 citation 可溯源；可选联网增强
- **读书记忆** — 跨书笔记 + **⌘K** 全局搜索，随时找回读过的内容
- **资讯** — RSS 同步、结构化简报与精读深聊
- **可扩展** — 可选 OpenAI / OpenRouter / Cursor 兼容 API；整书摘要导出 Markdown
- **两档摘要** — 每个 API 资源可分别配置正常/高级模型；开始摘要时选择档位，默认正常，高级未配置时自动回退正常模型

---

## 最近更新

### v0.10 — 阅读进度、摘要队列与操作更稳

- **阅读进度**：退出或切书后停在离开时那一段的开头；书架显示「在读 · n/m 段」；两本进度互不串味
- **阅读操作**：点翻段 / 复制 / 重新摘要不再误开关工具栏；翻段按钮钉在最右侧；工具栏「段列表」会钉住侧栏
- **摘要队列**：全书索引不再抢段摘要槽位；阅读面也能看到进行中 / 排队，不再出现「0 进行中 · n 排队」
- **书架**：右键即可整书重新分段；打开书不再弹出笔记 cancelled；周期性按钮 tooltip 已去掉

### v0.9 — 语义分段、书架与阅读更稳

- **语义结构分段**：序言与正文分开，短序不再并进第一章；在句末切开，不从句子中间截断
- **书架详览**：智能集合 + 网格/列表；阅读中侧栏只保留最近打开，整理与沉浸阅读分开
- **手动调界 / 重新分段**：拖动相邻段分界只重摘要这两段；整书可按 200–8000 字重新分段
- **两档摘要 + 分层索引**：正常/高级模型；摘要质检避免把原文「我」写成阅读助手；深聊用分层 rollup
- **更多格式与编码**：FB2 / DOCX / ODT / RTF / HTML / Markdown；GB18030 TXT；Identity-H CID PDF 正确抽中文
- **阅读进度**：跨段即时保存，退出不丢；按视口恢复；未读完不标已读完；布局抖动不跳回首页
- **引擎身份**：升级后自动换掉旧 sidecar，不再因切分版本相同而复用旧进程；OCR / 联网搜索设置重启后保留

### v0.8 — Windows 与 macOS 功能对等

- Windows 补齐资讯、Ctrl+K、笔记、Markdown 导出、完整设置与任务管理
- 阅读器结构化摘要、笔记抽屉、选区提问、深聊 token / 耗时 / TPS
- WinUI 惯用 NavigationView / 工具栏 / 抽屉，不复刻 Mac 贴边沉浸 chrome
- v0.8.1：修复 EPUB spine 解析

### v0.7 — Windows P0 与阅读器滚动修复

- WinUI 自包含发布（ZIP）与跨平台 `lumina-core` 适配
- 修复 macOS 阅读器跳转在滚动抑制期间丢失

### v0.6 — 更高可用的伴读体验

- **SQLite 跨线程串行化**，导入写入与 API 读不再竞态报错
- 摘要 **默认不自动开始**（设置可开），导入只分段，后台更可控
- 阅读器 **命中区域收窄**、书库侧栏可见性策略，误触更少
- 深聊 **token / 耗时 / TPS** 归因展示，云端与本地调用更可观测
- 可配置 Prompt、书库批量摘要启停（承接 v0.5 后的管控能力）

### v0.5 — 云端摘要、多书并发与阅读体验升级

- **OpenRouter / OpenAI 兼容**云端摘要，设置热更新与 JSON 解析更鲁棒
- **多书并发槽位等待**，Ollama 满负载时排队而非误切云端；摘要进度 Banner 实时展示
- 段列表**瘦 API + 按需 hydrate**，大书 reopen 更快；选区**发送到深聊**
- 书库**分类筛选**、导出重构（系统保存面板 + 中文文件名）；OCR 发布校验增强

---

## 普通用户 · 下载即用

> 你**不需要**安装 Python、uv、Xcode 或任何命令行工具。下载安装包，拖进「应用程序」即可。

### 下载

| 平台 | 要求 | 下载 |
|------|------|------|
| macOS 14+（Apple Silicon / Intel） | 约 250 MB 安装包（安装后约 450 MB）+ 首次 AI 模型 ~3 GB | **[GitHub Releases 下载 DMG](https://github.com/hezhenghui7338/Lumina/releases/latest)** |
| Windows 10/11 x64（P0） | ZIP 自包含目录 + 首次 AI 模型 ~3 GB | **[GitHub Releases 下载 Windows ZIP](https://github.com/hezhenghui7338/Lumina/releases/latest)** |

Release 页提供 **Lumina-*-macOS.dmg** 与 **Lumina-*-Windows-x64.zip**（GitHub Actions 构建）。Windows 与 macOS **功能对等**（WinUI 惯用交互：书库 / 阅读 / 笔记 / Ctrl+K / 资讯 / 设置 / 任务管理）。

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
3. **导入书籍** — 点「导入」，选择文件即可

当前支持的导入格式：

| 类型 | 扩展名 |
|------|--------|
| 电子书 | `.pdf` `.epub` `.mobi` `.fb2` |
| 办公文档 | `.docx` `.odt` `.rtf` |
| 网页 | `.html` `.htm` `.xhtml` |
| 文本 | `.txt` `.text` `.md` `.markdown` `.mdown` `.mkd` `.log` |

> **说明**：Ollama 是免费的本机 AI 运行时（类似本地版 ChatGPT 引擎）。Lumina 已内置阅读引擎，Ollama 仅负责 AI 摘要与对话，数据不出本机。
>
> 扫描 PDF 默认使用本地 OCR。若在「设置 → 文档识别」同时填写 OpenAI 兼容 Base URL、视觉模型和 API Key，Lumina 会优先逐页上传到该服务识别；云端失败会明确报错，不会静默改走本地。

### 日常使用

| 操作 | 方法 |
|------|------|
| 导入书 | 书库 → **导入**（亦可拖入书架） |
| 浏览书架 | 左侧智能集合 + 右侧网格/列表；点书进入阅读 |
| 阅读 / 深聊 | 选中书籍 → 左侧段列表 + 段摘要；触左段列表、触右笔记、触底提问（工具栏亦可收起段列表） |
| 跨书笔记 | 书库 → **全部笔记** |
| 跨书搜索 | **⌘K** |
| 资讯 | 顶部 **资讯** Tab → **同步 RSS** |
| 导出摘要 | 阅读器 → **导出** |
| 任务管理 | **设置** Tab → 查看 / 取消进行中的导入与摘要 |
| 设置 | **设置** Tab（语言、联网 provider、深色模式） |

> **说明**：**Cursor** 预设资源走 OpenAI 兼容 HTTP 路径（`POST /v1/chat/completions`），需在设置中配置代理 Base URL 与 API Key（Cursor 官方暂无原生 chat/completions endpoint）。默认亦支持 Ollama、OpenAI、OpenRouter 等。

### Windows 安装

1. 下载 **Lumina-*-Windows-x64.zip** 并解压  
2. 运行解压目录中的 **Lumina.exe**  
3. 若 SmartScreen 提示「Windows 已保护你的电脑」：点 **更多信息** → **仍要运行**（当前 Release 尚未 Authenticode 签名）

Windows 数据目录：`%APPDATA%\Lumina\`

### 数据在哪

全部在本机：

```
macOS:   ~/Library/Application Support/Lumina/
Windows: %APPDATA%\Lumina\
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

- macOS 14+（SwiftUI）或 Windows 10/11（WinUI 3）
- macOS：[Xcode 15+](https://developer.apple.com/xcode/)
- Windows：[.NET 8 SDK](https://dotnet.microsoft.com/download) + Visual Studio 2022（Windows 应用开发工作负载）
- [uv](https://docs.astral.sh/uv/)（Python **3.11+**）
- [Ollama](https://ollama.com) + `qwen3.5:4b`

### 本地开发

```bash
git clone <repo> && cd Lumina

# 安装 Python 依赖
just install

# 终端 A：Sidecar
just core

# macOS — Xcode：打开 apps/macos/Lumina.xcodeproj → ⌘R
# 或在 Scheme 中设置 LUMINA_CORE_DIR=$PWD/packages/lumina-core

# Windows — 见 apps/windows/README.md
#   $env:LUMINA_CORE_DIR = "$PWD\packages\lumina-core"
#   dotnet run --project apps/windows/Lumina/Lumina.csproj -p:Platform=x64
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
2. 输入版本号（如 `0.10.0`）运行
3. 在 Artifacts 或 tag Release 中下载 DMG

**本机构建（需与 macOS 版本匹配的 Xcode）**

macOS 15 用户：**不要**从 App Store 装最新 Xcode（可能要求 macOS 26+）。请从 [Apple 开发者下载页](https://developer.apple.com/download/all/) 安装 **Xcode 16.x**（支持 macOS 15）。

```bash
./scripts/build-release.sh
# 会先跑 just test-release 等价测试，通过后才打包
# 产出：dist/Lumina-0.10.0-macOS.dmg 与 .zip
```

打 tag 推送后会自动构建并上传到 Release：

```bash
git tag v0.10.0 && git push origin v0.10.0
```

### 文档

- [PRD](docs/PRD.md) · [TDD](docs/TDD.md)
- [Sidecar API](packages/lumina-core/README.md)

---

## 许可证

MIT
