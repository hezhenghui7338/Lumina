# Lumina 发布指南（维护者）

面向开发者，说明如何构建普通用户可下载的安装包。

## 产出物

| 文件 | 说明 |
|------|------|
| `dist/Lumina.app` | 内嵌 `lumina-core` 的 macOS 应用 |
| `dist/Lumina-{version}-macOS.zip` | 压缩包，可直接分发 |
| `dist/Lumina-{version}-macOS.dmg` | 磁盘映像，含拖入 Applications 引导 |

用户**无需**安装 Python、uv、Xcode。

## 前置条件

- macOS 14+
- Xcode 15+（`xcodebuild`）
- [uv](https://docs.astral.sh/uv/)

## 构建

```bash
./scripts/build-release.sh

# 指定版本号
LUMINA_VERSION=0.1.0 ./scripts/build-release.sh
```

## 构建步骤（脚本内部）

1. `uv sync --extra release` + PyInstaller → `packages/lumina-core/dist/lumina-core/`
2. `xcodebuild -configuration Release` → `Lumina.app`
3. 复制 sidecar 到 `Lumina.app/Contents/Resources/lumina-core/`
4. 打包 ZIP + DMG

## 验证清单

- [ ] 在未克隆仓库的 Mac 上，双击 DMG 安装后能打开 App
- [ ] 活动监视器中出现 `lumina-core` 进程（来自 App Resources）
- [ ] `curl http://127.0.0.1:17432/health` 返回 `ok`
- [ ] 安装 Ollama + 模型后可导入 TXT 并完成首段摘要
- [ ] 无需本机安装 uv / Python

## GitHub Releases

1. 打 tag：`git tag v0.1.0 && git push origin v0.1.0`
2. 上传 `dist/Lumina-0.1.0-macOS.dmg` 与 `.zip`
3. 更新 README 中的 Releases 链接

## 用户仍需 Ollama 的原因

AI 模型体积约 3 GB+，不适合打进主安装包。App 内引导用户安装 Ollama 并拉取 `qwen3.5:4b`。后续可考虑：

- 安装包内附带 Ollama.dmg
- 首次启动自动 `ollama pull`（Ollama 已安装时）

## 故障排查

**PyInstaller 失败**：`cd packages/lumina-core && uv sync --extra release && uv run pyinstaller lumina-core.spec --noconfirm`

**xcodebuild 失败**：确认 Xcode Command Line Tools：`xcode-select -p`

**Sidecar 未嵌入**：检查 `Lumina.app/Contents/Resources/lumina-core/lumina-core` 是否存在且可执行
