# Lumina for Windows (WinUI 3 · P0)

Windows 桌面壳：书库导入 → 分段摘要 → 阅读 / 深聊 → 设置 / Ollama。  
业务引擎复用仓库内 `packages/lumina-core`（localhost `127.0.0.1:17432`）。

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

## 发布包

在 Windows 上：

```powershell
.\scripts\build-release-windows.ps1
# 或指定版本
$env:LUMINA_VERSION = "0.7.0"
.\scripts\build-release-windows.ps1
```

产出：`dist\Lumina-{version}-Windows-x64.zip`（含 `Lumina.exe` + `lumina-core\`）。

## P0 范围

含：书库、阅读器、摘要 SSE、深聊 stream、设置、Onboarding。  
不含：资讯、全局搜索、全部笔记、Markdown 导出、完整任务管理 UI。
