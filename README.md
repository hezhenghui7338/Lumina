# Lumina

**Local AI Reading Companion · AI 伴读**

让阅读速度提升 5 倍，而理解深度提升 10 倍。

---

## 普通用户 · 下载即用

> 你**不需要**安装 Python、uv、Xcode 或任何命令行工具。下载安装包，拖进「应用程序」即可。

### 下载

| 平台 | 要求 | 下载 |
|------|------|------|
| macOS 14+（Apple Silicon / Intel） | 约 200 MB 安装包 + 首次 AI 模型 ~3 GB | **[GitHub Releases 下载 DMG](https://github.com/hezhenghui7338/Lumina/releases/latest)** |

若链接尚未发布，请让维护者运行 `./scripts/build-release.sh` 生成 `dist/Lumina-*-macOS.dmg` 后上传。

### 安装（两步）

1. 打开下载的 **`.dmg`**，将 **Lumina** 拖入 **Applications（应用程序）** 文件夹  
2. 从启动台或应用程序文件夹打开 **Lumina**

首次打开若提示「无法验证开发者」：**系统设置 → 隐私与安全性 → 仍要打开**。

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
| 阅读 / 深聊 | 选中书籍 → 左侧选段 → 下方输入问题 |
| 跨书搜索 | **⌘K** |
| 资讯 | 顶部 **资讯** Tab → **同步 RSS** |
| 导出摘要 | 阅读器 → **导出** |
| 设置 | **设置** Tab（语言、联网、深色模式） |

### 数据在哪

全部在本机，路径：

```
~/Library/Application Support/Lumina/
```

### 常见问题

**打不开 / 提示损坏？**  
系统设置 → 隐私与安全性 → 仍要打开；或右键 Lumina → 打开。

**导入失败？**  
确认 Ollama 已安装且在运行（菜单栏有 Llama 图标），并已下载 `qwen3.5:4b` 模型。

**内存较小？**  
在 Ollama 中改用 `qwen3.5:2b` 或 `qwen3.5:0.8b`，并在 Lumina **设置** 中调整（若已配置模型）。

**第一段摘要较慢？**  
首次把模型载入内存需 30 秒～2 分钟，属正常现象。

---

## 开发者

面向贡献者与从源码构建的同学。普通用户请只看上一节。

### 环境

- macOS 14+
- [Xcode 15+](https://developer.apple.com/xcode/)
- [uv](https://docs.astral.sh/uv/)（Python 工具链）
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
just test-live     # 需本机 Ollama
```

### 打开发布包（给普通用户）

在**有 Xcode 的机器**上执行：

```bash
./scripts/build-release.sh
# 产出：dist/Lumina-0.1.0-macOS.dmg 与 .zip
```

脚本会：PyInstaller 打包 `lumina-core` → Release 编译 `Lumina.app` → 内嵌引擎 → 生成 DMG/ZIP。详见 [docs/RELEASE.md](docs/RELEASE.md)。

### 文档

- [PRD](docs/PRD.md) · [TDD](docs/TDD.md)
- [Sidecar API](packages/lumina-core/README.md)

---

## 许可证

MIT
