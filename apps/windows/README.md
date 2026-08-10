# Lumina for Windows (WinUI 3)

Windows 桌面壳：与 macOS 功能对等（Windows 惯用交互），业务引擎复用仓库内 `packages/lumina-core`（localhost `127.0.0.1:17432`）。

## 功能

- **书库**：多文件导入、冲突处理、分类/摘要状态筛选、排序、收藏、批量操作、全部笔记入口、导出 Markdown
- **阅读器**：段列表、结构化摘要 / 原文+译文、字号、笔记抽屉、深聊 SSE（citation / metrics）、选区提问、导出
- **搜索**：`Ctrl+K` 跨书籍 / 段落 / 笔记，跳转原段
- **资讯**：RSS 同步、简报、精读、深聊、信源管理
- **设置**：语言、联网、模型资源池与优先级、Prompt、调试模式 → 任务管理
- **Onboarding**：引擎就绪 → Ollama 引导 → 进入书库

交互采用顶栏 `NavigationView`、工具栏与抽屉，不复刻 macOS 贴边沉浸 chrome。

## 要求

- Windows 10 1809+ / Windows 11
- [.NET 8 SDK](https://dotnet.microsoft.com/download)
- [Visual Studio 2022](https://visualstudio.microsoft.com/)（含 **Windows 应用开发** / Windows App SDK 工作负载）
- [uv](https://docs.astral.sh/uv/) + Python 3.11+（开发模式跑 sidecar）
- [Ollama](https://ollama.com) + `qwen3.5:4b`（本地摘要 / 深聊）

## 本地开发

```powershell
# 终端 A：引擎
cd packages\lumina-core
uv sync
uv run lumina-core

# 终端 B：UI
cd apps\windows
dotnet build Lumina\Lumina.csproj -c Debug -p:Platform=x64
dotnet run --project Lumina\Lumina.csproj -c Debug -p:Platform=x64
```

开发模式若未嵌入 sidecar，请设置：

```powershell
$env:LUMINA_CORE_DIR = "<repo>\packages\lumina-core"
```

数据目录：`%APPDATA%\Lumina\`

## 测试

服务层单测（无 WinUI 依赖，可在 macOS/Linux 用 .NET 9 跑）：

```powershell
dotnet test Lumina.Tests\Lumina.Tests.csproj -c Debug
```

完整 UI 验收需在 Windows 本机或 `release-windows` CI 上运行。

## 发布包

在 Windows 上：

```powershell
.\scripts\build-release-windows.ps1
# 或指定版本
$env:LUMINA_VERSION = "0.7.0"
.\scripts\build-release-windows.ps1
```

产出：`dist\Lumina-{version}-Windows-x64.zip`（含 `Lumina.exe` + `lumina-core\`）。

## 章程 0

导入、摘要、OCR、联网、切书、深聊均不得冻结 UI：网络与 JSON 在后台线程，SSE 批处理刷新，切页取消进行中任务，段列表不携带全书 `raw_text`。
