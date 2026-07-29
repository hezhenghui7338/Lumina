# lumina-core

Lumina 本地 AI 阅读引擎（FastAPI sidecar）。

**普通用户**：请使用 [仓库 README](../../README.md) 中的 DMG 安装包，无需阅读本文。

## 开发者

### 本地运行

```bash
uv sync --extra dev
uv run lumina-core
# http://127.0.0.1:17432/health
```

`dev` / `release` 已包含 OCR 依赖（`rapidocr` · `onnxruntime` · `pymupdf`）。仅装 OCR：`uv sync --extra ocr`。

### 测试

```bash
uv run pytest -m "not live and not live_chunk" -q
```

### 打包（内嵌进 Lumina.app）

```bash
uv sync --extra release
uv run pyinstaller lumina-core.spec --noconfirm
# 产出：dist/lumina-core/lumina-core
```

完整发布流程见 [docs/RELEASE.md](../../docs/RELEASE.md)。

## API 概览

| 端点 | 说明 |
|------|------|
| `GET /health` | 健康检查 |
| `POST /books/import` | 导入书籍 |
| `GET /books/{id}/segments` | 段列表 |
| `POST /books/{id}/chat` | 深聊（`stream:true` → SSE） |
| `GET /search?q=` | 跨书 FTS |
| `GET /news/brief` | 资讯简报 |

完整契约见 [docs/TDD.md](../../docs/TDD.md)。
