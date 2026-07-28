# Lumina macOS 客户端

**普通用户请阅读仓库根目录 [README.md](../../../README.md)** — 下载 DMG 安装即可，无需 Xcode 或命令行。

## 开发者

```bash
# 从源码运行（需 uv + Ollama）
open ../Lumina.xcodeproj   # ⌘R

# 打发布包（需完整 Xcode）
../../../scripts/build-release.sh
```

Release 版 App 会自动使用内嵌的 `Contents/Resources/lumina-core/`，Debug 版回退到 `uv run` + `LUMINA_CORE_DIR`。
