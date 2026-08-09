# Lumina 发布指南（维护者）

面向开发者，说明如何构建普通用户可下载的安装包。

## 产出物

| 文件 | 说明 |
|------|------|
| `dist/Lumina.app` | 内嵌 `lumina-core` 的 macOS 应用 |
| `dist/Lumina-{version}-macOS.zip` | 压缩包，可直接分发 |
| `dist/Lumina-{version}-macOS.dmg` | 磁盘映像，含拖入 Applications 引导 |
| `dist/Lumina-{version}-Windows-x64.zip` | Windows 自包含目录（`Lumina.exe` + `lumina-core\`） |

用户**无需**安装 Python、uv、Xcode / Visual Studio。

## 安装包体积（v0.2 精简版）

| 产物 | 目标大小 | 说明 |
|------|----------|------|
| `Lumina-{version}-macOS.dmg` | ≤ 300 MB | UDZO 压缩安装包 |
| `Lumina.app` | ≤ 500 MB | 安装后磁盘占用 |

Sidecar 已裁剪：冗余 OCR small 模型、非中英文 Babel 语言包。OpenCV（`cv2/.dylibs`）**不得**手动删除，否则扫描 PDF OCR 会失败。构建脚本会在体积超限时失败，并在 prune 后运行 `--smoke-ocr` 校验。Cursor provider 已改为 OpenAI 兼容 HTTP 路径，不再依赖 `cursor-sdk`；`prune-sidecar.sh` 仍会校验 sidecar 不含历史残留的 `cursor_sdk/` 目录。

## 前置条件

### macOS

- macOS 14+
- Xcode 15+（`xcodebuild`）
- [uv](https://docs.astral.sh/uv/)（Python **3.11+**，仓库根目录 `.python-version` 默认 3.11）
- [Ollama](https://ollama.com) 运行中且已拉取 `qwen3.5:4b`（release 测试含 live 用例）

### Windows

- Windows 10/11 x64
- [.NET 8 SDK](https://dotnet.microsoft.com/download) + Windows App SDK 工作负载
- [uv](https://docs.astral.sh/uv/)（Python **3.11+**）
- PowerShell 7+（推荐）

## 构建

### macOS

```bash
./scripts/build-release.sh

# 指定版本号
LUMINA_VERSION=0.7.0 ./scripts/build-release.sh
```

### Windows

```powershell
.\scripts\build-release-windows.ps1

$env:LUMINA_VERSION = "0.7.0"
.\scripts\build-release-windows.ps1
```

步骤：`pytest tests/unit` → PyInstaller → `prune-sidecar.ps1` → `--smoke-ocr` → `dotnet publish` → 嵌入 sidecar → ZIP。  
GitHub Actions：`Release Windows` workflow（`windows-latest`）。

## 构建步骤（脚本内部）

0. `pytest -m "not perf"`（单元 + e2e + live；失败则中止，不进入打包）
1. `uv sync --extra release` + PyInstaller → `packages/lumina-core/dist/lumina-core/`
2. `scripts/prune-sidecar.sh` 裁剪冗余 sidecar 文件并校验不含历史残留的 `cursor_sdk/`
3. `xcodebuild -configuration Release` → `Lumina.app`
4. 复制 sidecar 到 `Lumina.app/Contents/Resources/lumina-core/`
5. 打包 ZIP + DMG；断言 App ≤ 500 MB、DMG ≤ 300 MB

## 验证清单

- [ ] 在未克隆仓库的 Mac 上，双击 DMG 安装后能打开 App
- [ ] `Lumina.app` ≤ 500 MB，`Lumina-*-macOS.dmg` ≤ 300 MB
- [ ] `Lumina.app/Contents/Resources/lumina-core/_internal/` 不含历史残留的 `cursor_sdk/`
- [ ] 活动监视器中出现 `lumina-core` 进程（来自 App Resources）
- [ ] `curl http://127.0.0.1:17432/health` 返回 `ok`
- [ ] 安装 Ollama + 模型后可导入 TXT 并完成首段摘要
- [ ] 无需本机安装 uv / Python

## GitHub Releases

1. 打 tag：`git tag v0.7.0 && git push origin v0.7.0`
2. 上传 `dist/Lumina-0.7.0-macOS.dmg` 与 `.zip`
3. 更新 README 中的 Releases 链接

## 用户仍需 Ollama 的原因

AI 模型体积约 3 GB+，不适合打进主安装包。App 内引导用户安装 Ollama 并拉取 `qwen3.5:4b`。后续可考虑：

- 安装包内附带 Ollama.dmg
- 首次启动自动 `ollama pull`（Ollama 已安装时）

## 故障排查

**PyInstaller 失败**：`cd packages/lumina-core && uv sync --extra release && uv run pyinstaller lumina-core.spec --noconfirm`

**xcodebuild 失败**：确认 Xcode Command Line Tools：`xcode-select -p`

**Sidecar 未嵌入**：检查 `Lumina.app/Contents/Resources/lumina-core/lumina-core` 是否存在且可执行

## 代码签名与公证（后续）

当前 CI 使用 `CODE_SIGNING_ALLOWED=NO`，用户首次打开需右键「打开」。正式对外分发需 Apple Developer Program + `notarytool` 公证。

Windows 首发 ZIP **未做 Authenticode 签名**；SmartScreen 可能提示「仍要运行」。签名与 MSIX/安装器列为后续。
