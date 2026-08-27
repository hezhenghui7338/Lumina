# Lumina 技术设计文档（TDD v1.0）

**产品真源**：[PRD.md](PRD.md) · Local AI Reading Companion · AI 伴读  
**版本范围**：v1.0 Mac MVP  
**原则**：独立重写；算法与数据流参考 LocalAgent `summarize` / `news` / `web_search`，**不引入** LangGraph · Mem0 · Chroma 整栈。

---

## 0. 技术决策摘要

| 决策项 | v1.0 结论 | 理由 |
|--------|-----------|------|
| UI 响应性 | **永不卡住用户**（PRD 章程 0）：重活离事件循环 / 离 MainActor；列表 API 不含全文 | 最高原则 |
| Mac UI | **SwiftUI 原生** | 浅色主界面、动效、阅读体验；PRD 原则 8 |
| Windows UI | **WinUI 3（.NET 8）**（与 mac 功能对等） | 原生体验；与 mac 双壳，共享 `lumina-core` |
| AI / 文档引擎 | **Python `lumina-core` 本地 sidecar** | 快速移植 LA 分段/摘要/联网算法；与 Swift UI 解耦 |
| App ↔ Core 通信 | **localhost HTTP（JSON REST）** | 简单、可独立调试；后续可换 XPC |
| 数据库 | **SQLite**（`GRDB` Swift 读 + Core 写，或 Core 独占） | PRD 数据模型；跨平台铺路 |
| 向量检索（跨书 recall） | **sqlite-vec** + BM25 混合 | 轻量、本地、无额外服务 |
| OCR | **OpenAI 兼容云端视觉 API（可选）→ RapidOCR / PP-OCRv6（默认本地）** | 云端配置完整时优先；未配置才走本地；跨平台统一 |
| 文档解析 | **ebooklib** EPUB pipeline；PyMuPDF/pypdf · mobi · striprtf · python-docx · odfpy · PyMuPDF OCR | B1 |
| Ollama | 摘要/翻译：**httpx 直连**本地 Ollama | B10 |
| 深聊模型 | **推荐外部 API**（OpenRouter 等）；与摘要/翻译 **分开配置** | B4/B10 GPU |
| 联网搜索 | **证据充分性驱动**（非关键词）；源：DDG · Wikipedia · arXiv · Open Library · GitHub | B5 |
| 开源协议 | **MIT** | — |
| 书籍存储 | 导入时**复制**；`file_hash` 重复 → **提示是否覆盖**（与展示书名无关）；批量可跳过剩下所有重复书、仍导入新书 | B1 |
| 分段时机 | **导入即开始**分段+摘要 prefetch | B11 |
| 批量队列 | 10+ 本可同时导入；OCR/分段并发 **默认 1**，随模型配置可调 | B1 |
| 超大文件 | **>500MB 警告并拒绝** | B1 |
| 段失败 | `error` 态；**重试 3 次**后标记失败 | B2 |
| 磁盘 quota | 超长书 segment 缓存设**上限** | B11 |
| 翻译 v1 | **自动 LLM 翻译**，用户无感知；v1 不单独处理古文 | B3 |
| 深聊输出 | **LLM JSON mode** 结构化 `{answer, citations, web_refs}` | B6 |
| Token 长线程 | **分层索引 + 动态上下文组装**（见 §4.6） | B4 |
| 段内高亮 | v1.0 **整段闪高亮** | B6/B7 |
| 导出 | Markdown **默认完整含译文**；可选 `mode=sentences` 仅各段三句话；翻译对用户不可见 | B9 |
| Ollama 首次体验 | 参考 LocalAgent `la setup`（RAM 分档 + pull） | B10 |
| 资讯简报 | RSS **标题 + excerpt 规则截取** | N2 |
| 深聊线程 | 每书一个 thread | B4 |

---

## 1. 系统架构

```mermaid
flowchart TB
  subgraph macApp [Lumina.app · SwiftUI]
    LibraryUI[书库]
    ReaderUI[阅读器]
    ChatUI[深聊常驻区]
    NewsUI[资讯 Tab]
    SearchUI[⌘K 搜索]
    SettingsUI[设置]
  end

  subgraph sidecar [lumina-core · Python localhost]
    API[HTTP API]
    Ingest[Ingest]
    Chunker[Chunker]
    Summarize[Summarize]
    Translate[Translate]
    Chat[Chat + RAG]
    WebSearch[WebSearch]
    News[News]
    Jobs[JobQueue]
  end

  subgraph external [外部 · 可选]
    Ollama[Ollama]
    Tavily[Tavily]
    DDGS[ddgs]
  end

  subgraph storage [本机存储]
    SQLite[(SQLite)]
    Files[Books + Cache]
  end

  macApp <-->|REST JSON| API
  API --> Ingest --> Chunker --> Summarize
  Summarize --> Translate
  Chat --> Summarize
  Chat --> WebSearch
  News --> WebSearch
  API --> SQLite
  API --> Files
  Summarize --> Ollama
  Chat --> Ollama
  Translate --> Ollama
  WebSearch --> DDGS
  WebSearch --> Tavily
  Jobs --> Summarize
  Jobs --> Translate
```

### 1.1 分层职责

| 层 | 职责 | 不做 |
|----|------|------|
| **SwiftUI App** | 书库/阅读器/深聊 UI、Sidecar 生命周期、文件导入 UX | LLM prompt、分段算法、OCR |
| **lumina-core** | 摄入、分段、摘要、翻译、深聊、联网、资讯 sync、SQLite 写入 | 原生 UI |
| **SQLite + 文件** | 结构化元数据、段缓存、笔记、对话、FTS/向量索引 | 云端同步 |

### 1.2 Sidecar 生命周期

桌面壳**拥有** `lumina-core` 进程，用户不得被迫用活动监视器 / 任务管理器收尸。

1. App 启动 → 自动启动 sidecar（设置里本会话手动停止过则除外）。
2. 检测 `127.0.0.1:17432`：`GET /health` **短超时**（约 2s）。健康且身份匹配（`chunker_version` + `core_version` + 同一 bundled 二进制）→ 仅崩溃残留可复用；**health 超时但端口仍占用 = 卡死，必须杀掉监听 PID 再拉起**；版本/二进制过期同现有 `shouldReplaceOrphan`。
3. 绑定 `127.0.0.1:{port}`（默认 `17432`）。
4. App 退出 → `POST /shutdown`（短超时）→ SIGTERM **监听 PID + 本会话进程树** → 仍占端口则 SIGKILL。`stop()` 不得只 `terminate` 本会话 `Process` 句柄（复用孤儿时句柄为 nil，退出会变成空操作）。
5. 设置页（始终可见，非调试）：状态 + **停止** + **重启**。停止后本会话 `ensureRunning` 不再自动拉起。JobQueue 仍持久化，重启后 `recover_on_startup`。

---

## 2. 仓库结构

```
Lumina/
├── apps/
│   ├── macos/
│   │   └── Lumina/                 # SwiftUI Xcode project
│   │       ├── Features/           # Library / Reader / News / Search / Settings
│   │       ├── Services/           # CoreClient · SidecarManager
│   │       └── Design/
│   └── windows/
│       └── Lumina/                 # WinUI 3 · .NET 8（功能对等）
│           ├── Features/           # Library / Reader / Settings / Onboarding
│           ├── Services/           # CoreClient · SidecarHost · SseReader
│           └── Design/
├── packages/
│   └── lumina-core/                # Python ≥3.11
│       ├── pyproject.toml
│       ├── lumina_core/
│       │   ├── main.py             # FastAPI entry
│       │   ├── api/                # REST routes
│       │   ├── ingest/             # load PDF/EPUB/MOBI/text/HTML/RTF/DOCX/ODT/FB2
│       │   ├── chunker/            # 参考 LA chunker + chonkie
│       │   ├── summarize/          # 段摘要 + label + prefetch
│       │   ├── translate/          # LLM 翻译（非 deep-translator）
│       │   ├── chat/               # 深聊 + RAG + citation
│       │   ├── search/             # 跨书 recall + web
│       │   ├── news/               # RSS sync / rank / brief
│       │   ├── models/             # Ollama httpx router
│       │   ├── db/                 # SQLite schema + repos
│       │   └── jobs/               # 后台 prefetch 队列
│       └── tests/
├── docs/
│   ├── PRD.md
│   ├── TDD.md
│   └── design/
└── scripts/
    ├── dev.sh                    # 同时起 core + open Xcode
    └── bundle-core.sh            # PyInstaller for release
```

---

## 3. 数据层

### 3.1 存储根目录

```
~/Library/Application Support/Lumina/
├── lumina.db                       # SQLite 主库
├── books/                          # 导入文件副本或 symlink
│   └── {book_id}/
│       └── original.{pdf|epub|…}
├── cache/
│   └── segments/{book_id}/         # 段摘要 JSON 备份（可选，主存 DB）
├── news/
│   └── articles.sqlite             # 资讯独立库（或合并 lumina.db）
├── config.json                     # 非敏感 Settings（语言、联网 provider 等）
├── models.json                     # 模型资源池与路由（不含 API Key）
└── secrets.json                    # API Key / Tavily Key（0600，仅本机 core 读写）
```

### 3.2 SQLite Schema（v1.0）

```sql
-- 书籍
CREATE TABLE books (
  id            TEXT PRIMARY KEY,
  title         TEXT NOT NULL,
  author        TEXT,
  format        TEXT NOT NULL,          -- pdf|epub|mobi|txt
  file_path     TEXT NOT NULL,
  cover_path    TEXT,
  language      TEXT,                   -- 检测源语言
  target_language TEXT,
  translation_mode TEXT DEFAULT 'auto', -- auto|original|bilingual
  segment_count INTEGER DEFAULT 0,
  current_segment_index INTEGER DEFAULT 0,
  status        TEXT DEFAULT 'unread',  -- unread|reading|summarized|processing|error；processing 时公开 summarize_state=segmenting；error 为书架摘要维「导入失败」（含取消导入），不占未摘要/分段中/摘要中/已摘要；书架「未读/在读/已读完」按 last_opened_at + 段进度推导，不用此列
  index_status  TEXT DEFAULT 'idle',    -- idle|building|ready|error · 全书分层索引
  file_hash     TEXT,                   -- 缓存失效
  created_at    TEXT,
  updated_at    TEXT
);

-- 段
CREATE TABLE segments (
  id              TEXT PRIMARY KEY,
  book_id         TEXT NOT NULL REFERENCES books(id),
  idx             INTEGER NOT NULL,       -- 0-based 段序号
  chapter         TEXT,
  heading_path    TEXT,                   -- JSON 数组，部/章最多 2 项；段列表组树用
  page_range      TEXT,
  anchor_label    TEXT,                   -- 〔§… · 段 N · p.…〕
  raw_text        TEXT,
  summary_json    TEXT,                   -- {sentences[], bullets[], anchor}
  label           TEXT,                   -- ≤20 字浓缩标签
  translation     TEXT,
  summary_status  TEXT DEFAULT 'pending', -- pending|running|ready|error|failed
  UNIQUE(book_id, idx)
);

-- 笔记（必须挂段；孤儿笔记迁移时删除）
CREATE TABLE notes (
  id          TEXT PRIMARY KEY,
  book_id     TEXT NOT NULL REFERENCES books(id),
  segment_id  TEXT NOT NULL REFERENCES segments(id),
  quote       TEXT,
  content     TEXT NOT NULL,
  type        TEXT NOT NULL,              -- manual|highlight|ai
  created_at  TEXT
);

-- 全书分层摘要树（叶子可指向 segments）
CREATE TABLE summary_nodes (
  id                 TEXT PRIMARY KEY,
  book_id            TEXT NOT NULL REFERENCES books(id),
  level              INTEGER NOT NULL,     -- 0 = 全书总摘要
  parent_id          TEXT,
  sort_idx           INTEGER NOT NULL,
  segment_id         TEXT,
  segment_idx_start  INTEGER,
  segment_idx_end    INTEGER,
  chapter            TEXT,
  label              TEXT,
  summary_json       TEXT,
  status             TEXT DEFAULT 'pending'
);

-- 深聊会话
CREATE TABLE chat_sessions (
  id          TEXT PRIMARY KEY,
  book_id     TEXT NOT NULL,
  scope       TEXT DEFAULT 'book',        -- segment|book
  segment_id  TEXT,
  updated_at  TEXT
);

CREATE TABLE chat_messages (
  id          TEXT PRIMARY KEY,
  session_id  TEXT NOT NULL REFERENCES chat_sessions(id),
  role        TEXT NOT NULL,              -- user|assistant
  content     TEXT NOT NULL,
  citations_json TEXT,                    -- [{segment_id, label}]
  web_refs_json  TEXT,                    -- [{url, title}]
  created_at  TEXT
);

-- FTS5 跨书搜索（笔记 + 段摘要 + 书名）
CREATE VIRTUAL TABLE search_fts USING fts5(
  book_id, segment_id, note_id, kind, title, body,
  tokenize='unicode61'
);

-- sqlite-vec 段向量（可选 v1.0 spike 后启用）
-- CREATE VIRTUAL TABLE segment_embeddings USING vec0(...);
```

### 3.3 缓存失效

段摘要/翻译缓存失效条件（与 LA `segment_cache` 对齐）：

- `books.file_hash` 变化
- Ollama 模型名变化
- `target_language` / `translation_mode` 变化
- chunker 参数版本 bump（`CHUNKER_VERSION` 常量）

---

## 4. 核心流水线

### 4.1 书籍导入

```mermaid
sequenceDiagram
  participant App as SwiftUI
  participant API as lumina-core
  participant Ingest as Ingest
  participant OCR as CloudVision or RapidOCR
  participant DB as SQLite

  App->>API: POST /books/import {paths[]}
  API->>Ingest: detect format + extract text
  alt 扫描 PDF 文本层不足
    Ingest->>OCR: PyMuPDF 渲染页 → ocr_pdf
    OCR-->>Ingest: ## [p.N] 标注文本
  end
  Ingest->>API: annotated text + metadata
  API->>DB: INSERT book（file_hash 重复 → 409 提示覆盖）
  API->>API: **导入即触发** segment + summary + translation jobs
  API-->>App: {book_id, status: processing}
```

**导入策略（v1.0）**

| 规则 | 行为 |
|------|------|
| 文件存储 | 复制到 `books/{id}/` |
| 大小限制 | **>500MB → 警告并拒绝** |
| 重复检测 | 同 `file_hash` → App 弹窗**是否覆盖**；展示名可改，不参与去重。批量另可 **跳过** / **跳过剩下所有**（后续 409 不再弹窗，新书仍导入） / **取消剩余导入** |
| 批量导入 | 10+ 本可同时提交；每本独立 job |
| 分段时机 | **导入完成即开始**分段（不等打开书） |
| OCR/分段并发 | 默认 **1**（内部常量，用户不可配） |

**格式解析（Core）**

| 格式 | 库 | 备注 |
|------|-----|------|
| PDF（文本层） | **PyMuPDF 优先**，`pypdf` 回退 | 页码锚点；Identity-H/CID 无 ToUnicode 时 pypdf 会乱码 |
| PDF（扫描 / 乱码层） | **PyMuPDF + OpenAI 兼容视觉 API / RapidOCR PP-OCRv6** | 覆盖率 < 15% 或文本层判定为 CID 乱码时触发；云端配置完整时优先 |
| EPUB | **`ebooklib` 为核心**，自建解析 Pipeline（spine → 章节 → 纯文本 + § 锚点） | 不用 epub2txt |
| MOBI | `mobi` | 同 LA |
| TXT/Markdown | 内置 | `.txt/.text/.md/.markdown/.mdown/.mkd/.log`。**字节抽样**识别编码（BOM → UTF-8 合法且非乱码 → GB18030/Big5 → replace 评分汉字+中文标点 → charset-normalizer）。抽样用 IncrementalDecoder（`final=False`），64KiB 截在多字节中间不得判失败。抽样中段遇非法字节（电子书残留二进制，如 `0xd0 0x14`）不得整书报「无法识别文本编码」：用 `errors=replace` 按汉字与 `。，、` 密度认 UTF-8/GB18030/Big5。UTF-8 能解开不算数：Latin-1 误解的 GBK 再存成 UTF-8 须恢复为汉字。latin-1 不得作为中文成功路径；认不出则导入失败。锁定 codec 后 **IncrementalDecoder 滑窗**解码（`replace`，去掉 NUL），禁止 `read_bytes()` 全书。 |
| HTML/XHTML | 内置 `HTMLParser` | 去除脚本/样式，保留标题锚点与元数据 |
| RTF | `striprtf` | 纯文本 + title/author |
| DOCX | `python-docx` | 段落、标题、表格文本、核心元数据 |
| ODT | `odfpy` | 段落、标题、核心元数据 |
| FB2 | 内置 XML | 章节锚点 + title/author |

### 4.1a OCR 方案（云端优先、RapidOCR 本地默认）

**为何不用 Vision.framework**

| 维度 | Vision.framework | RapidOCR / PP-OCRv6 |
|------|------------------|---------------------|
| 架构 | Swift OCR → 回传 Core，**双端流水线** | 全在 `lumina-core`，与 ingest 一体 |
| 中文/古文扫描 | 一般 | LA 已验证，PP-OCRv6 更适合 |
| 跨平台 | 仅 Apple | Mac / Windows / Linux 同一套 |
| 与 LA 复用 | 需重写 | **直接参考** `ingest/ocr.py` |
| 依赖 | 零额外 | `rapidocr` + `onnxruntime` + `pymupdf`（可打包进 sidecar） |
| 页级进度 | 需 Swift 实现 | LA 已有 `on_progress` 回调 |

TDD 初版选 Vision 是为「Mac 零依赖」；在 **Python sidecar 已成立** 的前提下，该理由不成立，且增加 Swift↔Core OCR 回传复杂度。

**实现（参考 LocalAgent `ingest/ocr.py`）**

```python
# lumina_core/ingest/ocr.py — 独立重写，算法对齐 LA
RapidOCR(params={
    "Det.ocr_version": OCRVersion.PPOCRV6,
    "Rec.ocr_version": OCRVersion.PPOCRV6,
    "Det.lang_type": config.OCR_LANG,  # ch / en / …
})
# ocr_pdf: PyMuPDF 逐页渲染 → OCR → ## [p.N] 段落
```

**依赖**（`lumina-core[ocr]` extra）：

- `rapidocr-onnxruntime` 或 `rapidocr`
- `onnxruntime`
- `pymupdf`

**配置**

| 项 | 默认 |
|----|------|
| `OCR_LANG` | `ch`（简中；古文扫描书优先） |
| `OCR_TIER` | `medium`（同 LA 档位） |
| 触发阈值 | 文本层覆盖率 < 15%，或文本层判定为 CID/Identity-H 乱码 |
| `ocr_cloud_base_url` | 空；OpenAI 兼容 API 根地址 |
| `ocr_cloud_model` | 空；支持图片输入的视觉模型 |
| `ocr_cloud_api_key` | 空；仅存 `secrets.json`，API 返回 `***` |
| `ocr_cloud_timeout_seconds` | `60` |

**Provider 路由**：Base URL、模型和 Key 三项完整时逐页调用 `chat/completions`，以 JPEG Data URL 传图，并记录 `ocr_engine=openai-compatible/{model}`；任一项为空时使用 RapidOCR。云端 HTTP 401、429、超时、连接或响应格式错误会终止导入并通过 `ingest_failed` 显示，绝不自动回退本地。

**配置与探活 API**：`GET/PUT /settings` 管理非敏感配置与掩码 Key；`GET /settings/ocr/status` 检查本地依赖或云端 `/models` 连通性。macOS 与 Windows 设置页均提示“扫描页会上传云端”。

**进度 UX**：OCR 经 SSE 推送 `{book_id, page, total, message}`，消息区分本地/云端；App 显示局部进度，不 blocking 全屏。PDF 渲染和云端同步 HTTP 均位于 ingest 的 `asyncio.to_thread` 工作线程。TXT / 非 OCR 导入同样走 `ingest_progress`：`page/total` 为已处理字数（或文件字节）与总量；结构扫描不得等整步结束才发第一帧。CPU 队列占用时先发「排队等待分段…」。`--cpu-worker` 父进程看门狗：无进度 180s 杀子进程；单本墙钟 `max(1800s, pages×60s, MiB×30s)` 硬顶 8h（PDF 打开后按页数，否则按文件体积；TXT 字数进度不得当页数）。`ingest_error` 写清阶段与实际上限。

### 4.2 智能分段（Chunker）

导入后先恢复 **文档地图**（front-matter / bodymatter / back-matter）与 **结构树**（部/章 HARD，节 STRONG），再在同一角色、同一章内按整段自然段打包到 summarize hard max。默认档以规则为主；高级档对超长或无标点块再做 LLM 切点。不把全书逐句交给 LLM。

```
load_document
  → 结构标记分层（# 部 / ## 章 / ###+ 节；PDF 页码仅锚点）
  → 结构树 + 结构单元（EPUB nested TOC、PDF outline level、§/第N章）
  → 启发式角色；可选一次 summarize JSON 文档地图（超时回退）
  → 角色硬切（序/前言不得并入第一章）
  → 章内按整段自然段打包到 hard max；切点阶梯：章/角色 > 自然段 > 句号 > 语义
  → 高级档：LLM offset → 段/句吸附
  → DocumentSegment[] + chapter / heading_path / page 元数据
```

角色只存在于结构元数据，**不得**写入 `raw_text` / 读者可见锚点。同一章内每段不少于 `SEGMENT_HARD_MIN_CHARS = 200` 字；HARD 章标题空壳（含 `## [§…]` 与紧随的「第N章」行）必须并入**本章**后续正文至 ≥200。`SEGMENT_MIN_CHARS = 500` 仍约束同一角色内 TOC 碎屑与话题切碎片。角色变化与**跨章** HARD 不受 200/500 地板限制（短章不得吞下一章；整章或全书不足 200 字时允许短段）。用户 budget 的 `min_chars < 500`（目标约 200–416）时 500 碎屑地板让位于该 budget，但不得低于 200，除非整章不足。章内二次切分按 **章 > 自然段 > 句号 > 语义** 的硬阶梯：未超过 `max_chars` 的自然段不得劈开；句号只用于单段超长；embedding / 规则 novelty 只在段界上提前停。完整自然段优先于 0.6T 地板；章末或下一段整段放不进 max 时允许短块。有句末标点时禁止按字数在句中硬切。重平衡无法同时满足地板与 `max_chars` 时，优先遵守 `max_chars` 与段完整性，不得把全书并成一段。

**Lumina 参数（v1.0 默认）**

| 参数 | Ollama | OpenRouter | 其他云端 API |
|------|--------|------------|--------------|
| `reading_target_chars` | 2000 | 3500 | 4000 |
| `reading_hard_max`（target×1.5） | 3000 | 5250 | 6000 |
| prefetch workers | 1 | 4 | 4 |
| 短书阈值 | ≤12000 字不切段 | 同 | 同 |

导入与「重新分段」可带 `segment_tier: normal | advanced`（设置 `default_segment_tier` 控制导入默认档，缺省 `normal`）。正常档：结构树 + 整段打包到 hard max（章 > 段 > 句 > 语义）+ 现有 embed 链 + 文档地图 LLM。高级档：同上，再对超长/无标点块做 LLM 切点（offset 先吸附段、再句）。高级分段须用户确认。`join(raw_text) == 原文`，禁止 overlap / skip-window。

每个 API 资源可在 `models.json` 中设置 `chunk_target_chars`（`0` = 使用该 resource 的 provider 默认值；非 0 时范围为 **200–8000**）。导入分段与段摘要输入上限均取 **summarize 优先级链首资源** 的 budget；仅对新导入书籍生效。设置页与整书重新分段支持**手输**目标字数，并提供 **500 / 1000 / 1500 / 2000 / 2500** 快捷档；下限 **200**（Ollama 设置上限 4000，其他与重新分段为 8000）。整书「重新分段」允许把目标字数设为 **200–8000**（下限 200，便于短段精读）；API 与客户端输入框共用该范围。

设置页「智能测试上下文」按 **有效理解长度** 建议该值，而不是接口最大输入：把若干主题不同的短段拼到目标字数，模型必须同时答对 **第一段** 与 **最后一段** 的埋藏事实。只记得开头、丢掉末段视为该档失败（对应摘要/深聊里后面的上下文被忽略）。过关上限取 80%、封顶 3500 字写入 `chunk_target_chars`（下限 1500）。探测走 `POST /settings/resources/{id}/context-probe`，后台可取消，不自动保存。

环境变量覆盖（全局最高优先级）：`LUMINA_CHUNK_TARGET_CHARS`、`LUMINA_CHUNK_MAX_CHARS`（见 `resolve_chunk_budget()`）。

### 4.3 段摘要 + Label

摘要请求携带 `summary_tier: normal | advanced`（缺省为 `normal`）。`ModelResource.model`
保持为正常模型以兼容旧 `models.json`，可选 `advanced_model` 用于高级摘要；为空时回退
`model`。两档共用 `summarize.priority` fallback 链。`segments.summary_tier` 记录实际档位，
历史数据迁移为 `normal`。「开始摘要」携带新档位时仅对未完成段生效，已 ready
段保留原摘要与原档位。客户端点「开始摘要」默认提交 `normal`，点旁边箭头并确认后提交
`advanced`；悬停文字不得展开高级。「全书重新摘要」(`POST .../summarize/regenerate`) 才会
重置全部段（含 ready）并按所选档位重跑；客户端必须先向用户确认。SSE
`segment_ready` 同步返回 `summary_tier`。

**单次 LLM 调用产出**（减少延迟）：

```json
{
  "sentences": ["…", "…", "…"],
  "bullets": [
    {"label": "要点", "body": "1～2 句充实说明（40～120 字）…"}
  ],
  "notes": ["…"],
  "follow_ups": ["引导问题 1？", "引导问题 2？"],
  "label": "王安石变法背景",
  "anchor": "§第三章 · 段 5 · p.42-48"
}
```

Prompt 约束：label ≤20 字；sentences ≤3；bullets 3–7 条（每条 label ≤8 字、body ≥20 字）；notes 0–3 条（可选）；follow_ups 0–3 条。

**连续上下文**：
- `SegmentRepo` 仅查询当前段之前已 ready 的 `idx/chapter/summary_json`，不读取 `raw_text`。
- JobQueue 将上一章和本章前文摘要压缩为最多 1600 字符的背景包；章节元数据缺失时降级为最近前序摘要。
- 背景只用于人物、代词、时间线和因果消歧，prompt 明确禁止把背景事件写成当前段事实，身份不明确时保留不确定性。

**质量监督（仅书籍段摘要）**

1. schema/richness 通过后，`summarize/quality.py` 扫描所有用户可见摘要字段，按字段位置记录乱码替换字符、控制字符、模板泄漏、占位文本、正文等于标签、异常符号、机械重复及疑似截断。
2. 超过 1 个本地硬问题时直接拒绝候选摘要；恰有 1 个问题或软可疑信号时，使用 `summarize` profile 发起独立 JSON 质检调用，并用原文短片与候选摘要复核。质检调用失败时退回本地硬问题结果，不能让队列额外失败。
3. 本地与模型问题按字段和片段去重；合计问题数 `> 1` 时抛出质量错误，进入当前段内的 LLM 重试循环。下一轮 prompt 明确携带上轮问题字段、原因与短片段。
4. 质量门位于 `SegmentRepo.update_summary` 和 `segment_ready` 之前；未通过的候选摘要不会入库或短暂显示。调用共享现有 Router Semaphore，仍在 JobQueue 后台执行。
5. `summary_llm_attempts` 只记录摘要生成轮次；质检耗时计入摘要 LLM 总耗时。资讯/文档 Markdown 摘要不在本阶段范围。

**Prefetch 与失败策略（v1.0）**

```
pending → running → ready | error（重试≤3）→ failed
```

- **按设置启动**：segment 切分完成后入库；仅在 `auto_start_summary=true` 时立即启动摘要链
- 后台 JobQueue：同书仅保留一个摘要 job 并按 `idx` 链式推进，不同书可并行；总模型并发仍由 provider Semaphore 限流
- 用户打开书时：若段 1 已 ready → 直接呈现；否则 skeleton 等待
- 用户跳转未 ready 段：继续该书摘要链，但不越过更早的 pending/error 段
- **失败重试**：每段最多 **3 次**；仍失败 → `summary_status=failed`，随后继续下一段；段列表显示 error，可手动重试
- **磁盘 quota**：单书 segment 缓存（摘要+译文+原文）默认上限 **2GB**（可配置）；超限 LRU 淘汰最旧未读段缓存
- 进度：SSE `GET /books/{id}/events`

**段摘要 LLM 输出（JSON mode）**

```json
{
  "sentences": ["…"],
  "bullets": [
    {"label": "要点", "body": "充实说明…"}
  ],
  "notes": [],
  "follow_ups": ["可追问的问题？"],
  "label": "王安石变法背景",
  "anchor": "§第三章 · 段 5 · p.42-48"
}
```

旧格式 `bullets: ["标签：内容"]` 仍可解析；新生成须为 `{label, body}` 对象数组。

### 4.4 自动翻译（用户无感知）

- v1.0：**不单独做语种检测/古文特殊处理**；目标语言 ≠ 用户设定语言时，**自动 LLM 翻译**
- 翻译是系统能力，**无用户可见按钮或开关**（书详情高级设置除外）
- 翻译 job 使用 **`translate` 模型配置**（默认本地 Ollama）
- 与摘要 prefetch 并行；优先级低于摘要（见 §4.5a）
- 术语一致性：书级 glossary 写入 `books.metadata_json`
- UI：外文书 / 需翻译书自动呈现译文；用户只读内容，不感知「翻译层」

### 4.5 模型路由与任务优先级（v1.0）

**三套独立模型配置**（`config/models.yaml`）：

| 用途 | 默认 Provider | 说明 |
|------|---------------|------|
| **chat**（深聊） | **外部 API 推荐**（OpenRouter 等） | 响应快、上下文长；Local First 仍可用 Ollama |
| **summarize**（段摘要+label） | **Ollama 本地** | 零账单主路径 |
| **translate** | **Ollama 本地** | 与 summarize 可同模型 |

**GPU / Job 优先级**（高 → 低）：

```
深聊 (chat)  →  段摘要 (summarize)  →  翻译 (translate)
```

- 用户发起深聊 → **暂停**低优 prefetch job，优先响应 chat
- 深聊走 `chat` 配置；摘要/翻译走各自 Ollama 配置
- OCR/分段 CPU 任务与 LLM job 分池

### 4.6 深聊（文档 + 联网 + 长线程）

```mermaid
flowchart TB
  Q[用户问题] --> DCA[动态上下文组装]
  HI[分层索引] --> DCA
  Q --> ES{证据充分性评估}
  ES -->|充分| LLM
  ES -->|不足| WebRoute[按领域选源检索]
  WebRoute --> LLM
  DCA --> LLM
  LLM --> JSON[JSON mode 输出]
```

#### 4.6.1 分层索引 + 动态上下文组装（Hierarchical Index + DCA）

全书摘要完成后，后台 Job `book_index` 将段摘要按章优先打包到 `resolve_chunk_budget().max_chars`，对超预算窗口再摘要，递归直到一层能塞进单段预算，得到 L0 总摘要，写入 `summary_nodes`。`books.index_status`：`idle | building | ready | error`。

| 层级 | 内容 | 用途 |
|------|------|------|
| L0 书级 | 全书总摘要（`summary_nodes.level=0`） | 全局理解；始终注入全书 scope |
| L1 分摘要 | 中间聚类节点 + 命中段摘要 | 定位相关章/段 |
| L2 证据级 | 命中段原文摘录（按 id 读取，禁止拉全书 `raw_text`） | 原文溯源 |

**召回顺序**：总摘要 → 分摘要 → 原文，用尽 chat 文档预算（默认约 10k 字）即停。书内 FTS 选段，沿命中叶子向上带父节点。

**动态上下文组装**：`POST /books/{id}/chat` 的 `scope=segment|book`（默认 segment）。全书且 `index_status != ready` → 409「全书索引生成中」。切段只更新 DCA，不新开 thread。

#### 4.6.2 证据充分性驱动的联网（Evidence Sufficiency）

流程：

1. 先组装本地文档上下文（当前段 + 邻段 + 书内 FTS top-k；全书 scope 为 L0 → L1 → 命中原文）
2. 用户消息含 `http(s)://` → **必抓**这些 URL（最多 2 页、每页约 1200 字、超时 8s）
3. 若本地上下文无法高置信回答（过短、与问题字面重叠低、或明确外部意图如背景/史实/术语/最新）→ 按领域检索，并抓取 top 命中正文
4. 「总结本段」等纯文档操作在上下文足够时不上网
5. 设置 `web_search_enabled` 可关（默认开）；关闭、超时或无网 → 仅文档

按问题**意图与领域**选源（可并行）：

| 领域信号 | 检索源 |
|----------|--------|
| 通用事实/背景 | **Wikipedia** + DuckDuckGo |
| 学术/论文 | **arXiv** + DDG |
| 书籍/作者元数据 | **Open Library** |
| 代码/项目 | **GitHub** + DDG |
| 默认 | DuckDuckGo |

- 设置中可关联网；无网仅本地
- 每轮最多 1 轮联网检索；注入 snippet + 正文摘录，结果标 `[网]`
- 文档预算预留约 2500 字给联网摘录；SSE 检索前发 `status`

#### 4.6.3 深聊 JSON 输出

LLM **JSON mode** 强制结构：

```json
{
  "answer": "…",
  "citations": [{"segment_index": 5, "label": "[段 5]"}],
  "web_refs": [{"title": "…", "url": "…"}],
  "evidence_sufficient": true
}
```

- Swift 解析后渲染可点击 citation；v1.0 跳转 **整段闪高亮**
- 源约束：书中事实必须有 citation；联网内容走 `web_refs`

**对话线程**：每书一个 thread；切段更新 DCA 输入，不新开 thread。

### 4.7 跨书 Recall（⌘K）

v1.0 实现路径：

1. **FTS5** 索引：`books.title`、`segments.summary_json`、`notes.content`
2. 搜索：`search_fts MATCH ?` + 按 kind 分组
3. v1.1 增强：sqlite-vec 语义召回

Swift：`SearchView` → `GET /search?q=…` → 跳转 `ReaderView(bookId, segmentId)`

### 4.8 资讯 lite

复用 LA 算法，简化存储：

| 模块 | 参考 | Lumina |
|------|------|--------|
| sync | `news/sync.py` + `rss.py` | `POST /news/sync` |
| store | `news/store.py` | `news_articles` 表 |
| rank | `news/rank.py` | 规则排序，无 LLM |
| brief | `news/brief.py` | `GET /news/brief` — **标题 + RSS excerpt 规则截取**，不用 LLM |
| 精读 | `news/read.py` + trafilatura | 单篇 → 临时 segment + 复用 Chat |

**不做**：`schedule` 定时 sync（v1.1）

**并行**：书库后台摘要/翻译与资讯 sync · 精读 · 深聊互不抢占，可同时进行（共享本机 Ollama 并行度上限）。

---

## 5. HTTP API 概要（v1.0）

Sidecar 绑定 `127.0.0.1` only；无认证（本机进程）。

### 5.1 书籍

| Method | Path | 说明 |
|--------|------|------|
| GET | `/health` | Sidecar 存活 |
| POST | `/books/import` | 导入文件/文件夹；**409** + `{existing_book_id}` 若 `file_hash` 重复 |
| POST | `/books/{id}/import/overwrite` | 用户确认覆盖后重新导入 |
| GET | `/books` | 书库列表；`?filter=all\|unread\|reading\|finished\|idle\|segmenting\|summarizing\|summarized\|error\|favorite\|<分类>`；`summarize_state` 含 `segmenting`（`status=processing`）；`filter=error` 为导入失败（`status=error`，含取消）；失败书不进入 idle/segmenting/summarizing/summarized；`?sort=recent\|added\|title\|segments\|progress\|favorite` |
| GET | `/books/categories` | 固定 LLM 主分类枚举 |
| PATCH | `/books/{id}` | 更新收藏 / 分类 / 标题 |
| DELETE | `/books/{id}` | 删除书及本地副本、摘要、笔记 |
| POST | `/books/{id}/classify` | 后台 LLM 重新分类 |
| GET | `/books/{id}` | 书籍详情 |
| PATCH | `/books/{id}/reading-progress` | 更新当前段进度 |
| GET | `/books/{id}/segments` | 段列表（含 label、summary_status、heading_path；默认不含 raw_text） |
| GET | `/books/{id}/segments/{idx}` | 单段详情 |
| GET | `/books/{id}/segments/{idx}/boundary` | 相邻两段可吸附切点（`candidates`，不含拼接全文）；点击调界以 POST 为准，客户端不再用 candidates 步进 |
| POST | `/books/{id}/segments/{idx}/boundary` | 移动与下一段的分界；body `{ left_char_count }`（点击处的 Unicode 码点偏移，服务端吸附）；只重摘要这两段；SSE `segment_boundary_moved` |
| POST | `/books/{id}/open` | 打开书（订阅 SSE；**不触发**分段，导入时已 queue） |
| POST | `/books/{id}/segments/{idx}/retry` | 手动重试单段摘要；可选 `summary_tier`，缺省沿用原档位 |
| POST | `/books/{id}/segments/retry` | 批量重试段摘要（body: `{ indices: number[], summary_tier?: normal \| advanced }`） |
| POST | `/books/{id}/summarize/start` | 开始/恢复未完成摘要；`summary_tier` 仅作用于未摘要段，不覆盖 ready |
| POST | `/books/{id}/summarize/regenerate` | 全书强制重新摘要（含 ready 段，覆盖已有摘要）；body 可选 `summary_tier`，默认正常。高成本操作，客户端须先确认 |
| POST | `/books/{id}/resegment` | 整书重新分段；body `{ chunk_target_chars }` 范围 **200–8000**；清空摘要/笔记/本书对话 |
| POST | `/books/{id}/resegment/cancel` | 取消进行中的重新分段，保留原段落数据 |
| GET | `/books/{id}/events` | SSE：段摘要/翻译 progress |

### 5.2 阅读与 AI

| Method | Path | 说明 |
|--------|------|------|
| POST | `/books/{id}/chat` | 深聊（stream SSE；`scope=segment\|book`） |
| GET | `/books/{id}/chat/sessions` | 会话列表 |
| POST | `/books/{id}/export` | 导出 Markdown；body `{ include_notes?, mode?: full\|sentences }`，默认 `full` 含译文；`sentences` 仅各段三句话（忽略笔记） |
| GET | `/books/{id}/segments/{idx}/listen-script` | 听稿；`mode=summary\|detailed\|original`（summary=简要摘要，detailed=完整摘要）。summary/detailed **只读摘要列**，禁止为听简要/完整摘要读 `raw_text`。detailed 含要点、不含 notes。朗读在客户端用系统语音，无 `POST .../speech` |
| GET | `/books/{id}/original-search?q=` | 书内原文查找。只扫 `raw_text`（不搜摘要/译文/笔记）；`asyncio.to_thread`；响应 `{query, hits, truncated}`，hit 含 `segment_index`、`start`/`end`（Unicode）、`start_utf16`/`end_utf16`、`snippet`；**不含** `raw_text`。空查询 → `hits=[]`。默认最多 80 条 |

### 5.3 笔记与搜索

| Method | Path | 说明 |
|--------|------|------|
| POST | `/notes` | 创建笔记（`segment_id` 必填；须属于该书） |
| GET | `/notes?book_id=&segment_id=` | 有 `book_id` → 书内列表（可按段筛）；无 → 跨书列表 |
| DELETE | `/notes/{id}` | 删除单条笔记（同步清理 FTS） |
| GET | `/search?q=` | 跨书 FTS（笔记 + 段摘要 + 书名；不是书内原文 Find） |

列表响应每条含 `segment_index`、`segment_label`；跨书时另含 `book_title`（不含 `raw_text`）。

### 5.4 资讯

| Method | Path | 说明 |
|--------|------|------|
| GET/POST | `/news/sources` | RSS 源管理 |
| POST | `/news/sync` | 手动同步 |
| GET | `/news/brief` | 今日简报 |
| POST | `/news/articles/{id}/chat` | 单篇深聊 |

### 5.5 设置

| Method | Path | 说明 |
|--------|------|------|
| GET/PUT | `/settings` | 三 Profile 模型、语言、web 开关；各 API 资源含 `concurrency` |
| GET | `/settings/ollama/status` | 连接检测 + RAM 分档推荐模型 + pull 状态 |
| POST | `/settings/ollama/setup` | 参考 LA `la setup`：检测/安装/pull |
| POST | `/settings/resources/{id}/context-probe` | 202 后台测有效上下文（多段拼接后末段是否仍被理解） |
| GET | `/settings/resources/{id}/context-probe` | 探测状态；建议 `recommended_chars`，不自动写入设置 |
| POST | `/settings/resources/{id}/context-probe/cancel` | 取消进行中的探测 |

---

## 6. SwiftUI 架构

### 6.1 阅读器状态（ReaderViewModel）

```swift
@MainActor
final class ReaderViewModel: ObservableObject {
  @Published var book: Book
  @Published var segments: [SegmentRow]      // heading_path 组树（最多 3 层）+ label
  @Published var currentSegment: SegmentDetail?
  @Published var chatMessages: [ChatMessage]
  @Published var chatScope: ChatScope = .segment

  func openBook() async       // POST /open + subscribe SSE（消费导入时已 queue 的段）
  func selectSegment(_ idx: Int) async
  func sendChat(_ text: String) async  // stream SSE
}
```

听文本：`ListenSession`（macOS `ObservableObject` / Windows 会话对象）管连播、倍速与离开即停；系统引擎本地拼稿并调用本机语音包。设置可打开 VoiceOver Utility（macOS 15+）或 `ms-settings:speech`（Windows）引导下载系统语音包；客户端**不代下**音库。切书走 `cancelAllTasks()` / `OnNavigatedFrom` 时必须 `stop()`。 sidecar **不发起**外网 TTS。

### 6.2 布局映射 PRD §3.2

```
ZStack
├── SegmentContentView（摘要 + 原文/译文；始终全宽）
├── NotesDrawer（渐进披露 · 右侧；上下让开顶底栏）
├── ChatDrawer（渐进披露 · 底部；停在底栏之上）
├── TopChromeBar（overlay；恒定 inset，显隐不得位移正文）
├── ListenMiniBar（播放中始终可见；chrome 隐藏时也保留）
├── SegmentCoverPage（底栏「段列表」自底上滑；停在底栏之上；再点段列表 / Esc / 选段关闭）
└── BottomFunctionBar（overlay；段列表 / 笔记 / 深聊 / 显示）
```

- 段列表是覆盖层，不是内嵌侧栏，不得挤压阅读区。底栏打开目录（自底上滑、不盖住底栏）；再点段列表 / Esc / 选段关闭。打开笔记或深聊时关掉目录。深聊 / 笔记仍为抽屉。阅读中不提供「最近」书库列表，切书走书架。无贴边图标、无触边 250ms dwell。字号与纸色走底栏「显示」popover；纸色不得改 `preferredColorScheme`。
- 段切换：`currentSegment` 更新；Chat 历史按 **book** 保留（PRD）
- **Citation 跳转 + 整段闪高亮（v1.0）**：
  1. `selectSegment(idx)` 切换段列表与内容区
  2. `SegmentContentView` 对整段容器施加 **flash 背景动画**（~400ms 琥珀色 fade-out）
  3. **不做**句级 offset 高亮；选区提问仅注入上下文，跳转仍整段闪高亮

### 6.3 书籍视图（占位）

`ReaderView` 顶栏 SegmentedControl：`段阅读 | 全书`  
全书 Tab v1.0 显示 placeholder + 「即将推出」；v1.1 与产品方设计后实现。

---

## 7. 模型集成（三 Profile + Ollama Setup）

### 7.1 三 Profile 配置（`config/models.yaml`）

```yaml
resources:
  - id: ollama
    provider: ollama
    model: qwen3.5:4b
    base_url: http://localhost:11434
    concurrency: 2                # 建议 ≤ OLLAMA_NUM_PARALLEL
  - id: openrouter
    provider: openrouter
    model: anthropic/claude-sonnet-4
    base_url: https://openrouter.ai/api/v1
    concurrency: 4
  - id: cursor
    provider: cursor
    model: composer-2.5
    concurrency: 8

chat:
  priority: [openrouter, ollama]

summarize:
  priority: [ollama, openrouter]
```

听文本由客户端系统语音包合成（与 `lumina_core.tts.script.build_listen_script` 对齐拼稿）。设置打开 VoiceOver Utility / `ms-settings:speech` 引导下载，客户端不代下音库。sidecar **不提供** `POST .../speech`，不缓存云端 mp3。

### 7.2 ModelRouter（Core）

参考 LA `models/router.py`；按 Profile 路由：

```python
class ModelRouter:
    def for_profile(self, profile: Literal["chat", "summarize", "translate"]) -> ModelRouter

    async def chat(self, messages, *, stream=True, json_mode=False) -> AsyncIterator[str]
    async def complete(self, prompt, *, json_mode=False) -> str
```

| Profile | 默认后端 | JSON mode |
|---------|----------|-----------|
| `chat` | OpenRouter / OpenAI-compatible | 深聊结构化输出 |
| `summarize` | Ollama `POST /api/chat` | 段摘要 + label |
| `translate` | Ollama | 纯文本译文 |

- Ollama 流式：SSE 解析 `message.content` delta
- 外部 API：`httpx` + OpenAI-compatible；Key 由 core `secrets.json` 持久化，启动时加载；开发可用 `LUMINA_*_API_KEY` 环境变量覆盖

### 7.3 Ollama 首次体验（参考 LocalAgent `ollama_setup.py`）

| 步骤 | 行为 |
|------|------|
| 检测 | `which ollama` + `GET /api/tags` |
| RAM 分档 | `sysctl hw.memsize` → 推荐 `qwen3.5:9b` / `4b` / `0.8b` |
| 未安装 | 引导打开 ollama.com/download 或运行 install.sh |
| 未 pull | `ollama pull {model}` + 进度回调 → SSE 推 App |
| 跳过 | 用户可跳过；AI 功能灰显 |

设置 → API 资源 → 编辑 Ollama 资源 → `GET /settings/ollama/status` → 必要时安装 / `ollama pull`。首次 spotlight 不引导 Ollama。

### 7.4 模型档位（PRD §7.5）

| 系统内存 | 推荐模型（summarize/translate） | 检测 |
|----------|--------------------------------|------|
| ≥18GB | `qwen3.5:9b` | `sysctl hw.memsize` / Swift |
| ≥10GB | `qwen3.5:4b` | 同 |
| 4–8GB | `qwen3.5:0.8b` | UI 提示能力受限 |

---

## 8. 后台任务与并发

**硬约束（PRD 章程 0 · 永不卡住）**：

- `async` HTTP handler **禁止**同步 CPU / 网络 / 大文件 I/O；必须 `asyncio.to_thread` 或投递 JobQueue。
- 大文件 ingest/resegment 的 decode / chunk / persist **须在 sidecar 子进程**执行（`--cpu-worker`）。`to_thread` + 协作式 `sleep` 不能让出 CPython `decode`、`re.finditer`、FTS 的 GIL；导入期间 `/health`、书库、资讯、设置必须可响应。
- 章标（`BARE_CHAPTER`）只对短行 `match`；禁止对超长正文行或全书跑嵌套装饰符正则。换行扫描不得对每个 `\n` 从文件头 `rfind`。
- cpu-worker 子进程无进度 180s，或单本墙钟 `max(1800s, pages×60s, MiB×30s)`（顶 8h）必须失败，不得停在「分段中」。PDF/OCR 按页数拉长墙钟；TXT 字数进度不得当成页数。
- TXT 解码与分段 **禁止全书 `str` 常驻**：峰值 RAM = 窗口 + 当前段 + 一批 INSERT；覆盖校验用偏移首尾相接，禁止 `join(raw_text)` 全书。
- `GET /books/{id}/segments` **默认不含** `raw_text`；原文仅 `GET .../segments/{idx}`。目录含 `heading_path`（0–2 个标题）；客户端用已加载瘦段表组最多 3 层树。禁止把全书 `document_tree` 放进书列表/详情。旧段无 `heading_path` 时从 `chapter` 按 ` · ` 拆并去掉 `§`，不强制重新分段。
- `GET /books/{id}/original-search` **禁止**同步扫库；**禁止**在 hits 中返回 `raw_text`。
- `segment_ready` SSE 须携带 UI 所需摘要字段；客户端 **禁止** 为此再拉全量段表。
- 手动调界只改相邻两段 `raw_text`；客户端在拼接原文上点击后 POST `left_char_count`（服务端吸附），不再拖动或步进 candidates；SSE `segment_boundary_moved` 后客户端补丁这两行，禁止整表 reload。
- Swift：网络收发与大 JSON 解码不得堵 MainActor；切书请求须可取消。

**三队列分池**：

| 队列 | 任务 | 默认并发 | 优先级 |
|------|------|----------|--------|
| **CPU** | ingest · OCR · chunk | 1 | 中 |
| **Ollama** | 段摘要 prefetch · 翻译 prefetch | **2**（可配置 1–4） | 摘要 > 翻译 |
| **Cursor** | summarize fallback · OpenAI 兼容 HTTP | **8**（可配置 1–8） | 摘要 fallback |
| **Cloud** | OpenAI / OpenRouter 等 | 4 | 摘要 fallback |

**Router 层 Semaphore**：chat、summarize、translate 经 `ProfileModelRouter` 的调用共享按 **resource id** 的并发槽。JobQueue worker 数 = 摘要链各资源 `concurrency` 的 **max**（默认 `max(2,8,4)=8`）；Ollama 槽满时立即 fallback Cursor，不再等 12s 超时。

**优先级**（高 → 低）：`深聊 (chat) → 段摘要 (summarize) → 翻译 (translate)`

| 场景 | 行为 |
|------|------|
| 导入完成 | 按设置决定是否开始摘要；同书段 0…N 链式生成，跨书并行 |
| 用户打开书 | 若段 1 ready → 直接呈现；否则 skeleton + SSE 等待 |
| 用户跳转未 ready 段 | 继续该书链，不越过未完成前序段 |
| 用户发起深聊 | **暂停** Ollama prefetch；chat 完成后恢复 |
| 段摘要失败 | 重试 ≤3 次 → `failed` 后继续后段；`POST .../retry` 手动重试 |
| 批量导入 10+ 本 | 每本独立 CPU job；Ollama 资源默认并发 2（在 API 资源编辑中可调） |

JobQueue：`asyncio.PriorityQueue` + worker pool；每书一个摘要链锁，完成或最终失败时调度下一段；job 状态持久化 SQLite，Sidecar 重启可恢复。SQLite 启用 **WAL** + `busy_timeout`。

---

## 9. 非功能需求映射

| PRD 指标 | 技术方案 |
|----------|----------|
| **永不卡住用户** | 瘦段列表 API；增量 SSE；`to_thread`/JobQueue 保护事件循环；CoreClient 解码离 MainActor；请求可取消 |
| 首段 ≤15s | 仅生成 segment[0] summary+label；短 prompt |
| 段切换 ≤200ms | 段内容已缓存在 SQLite；列表不含 raw_text，按需单段拉取 |
| 深聊首 token ≤3s | 流式 SSE；RAG 限制 top-k=3；token 批处理刷新 UI |
| 离线书库 | Core 无网时跳过 web_search |
| 隐私 | Sidecar 只 bind 127.0.0.1；keys 存 `secrets.json`（0600） |

---

## 10. 开发分期（对齐 PRD Wave）

### Wave 1 — Dogfood

- [x] Sidecar skeleton + SQLite schema
- [x] Ingest PDF/TXT + chunker
- [x] Segment summary + label + prefetch
- [x] SwiftUI Reader（段列表 + 段内容 + 常驻 Chat）
- [x] Ollama chat + 段级 citation
- [x] SSE progress

### Wave 2 — Alpha

- [x] EPUB/MOBI + RapidOCR 扫描 PDF（OCR 为 optional extra `[ocr]`）
- [x] 自动翻译 job
- [x] 联网深聊（ddgs）
- [x] 笔记 + FTS 跨书搜索（trigram tokenizer）
- [x] Markdown 导出
- [x] 资讯 lite（RSS sync + 规则 brief）
- [x] 浅色主题 DesignSystem + Tab（书库/资讯）+ ⌘K 搜索

### Wave 3 — Beta / Polish（MVP 验收收口）

- [x] 设置 Tab（目标语言、联网、Ollama 状态、浅色/深色/系统）
- [x] 阅读器笔记侧栏 + 深聊「存为笔记」
- [x] 笔记必须挂段；书内筛选跳段 + 书库全部笔记跨书列表
- [x] 选区提问（剪贴板引用 + `quote` API）
- [x] 导出可选含笔记
- [x] 导出可选仅各段三句话
- [x] 资讯精读视图 + 单篇深聊 SSE（`/news/articles/{id}/chat`）
- [x] Onboarding spotlight（导入 / 选书 / API / 摘要 / 切换 / 深聊 / 笔记，可跳过）
- [x] Xcode 工程同步 Wave 2/3 全部 Swift 源文件

---

## 11. 测试策略

> **完整指南**：[docs/testing.md](testing.md) · [chunking-review](testing/chunking-review.md) · [snapshot-guide](testing/snapshot-guide.md) · [refusal-corpus](testing/refusal-corpus.md)

| 层 | 工具 | 范围 |
|----|------|------|
| lumina-core | pytest | chunker、summary parse、citation 提取、rank、web_search mock |
| lumina-core | pytest `@live_chunk` | **长文切割 + 真实 Ollama 摘要段 0/1**（唯一 PR Live 例外） |
| lumina-core | pytest `@live`（nightly） | 性能、corpus 抽检 |
| SwiftUI | XCTest + swift-snapshot-testing | ViewModel、DesignSystem Snapshot（v1.0） |
| SwiftUI | XCUITest | 黄金路径 3–5 条 |
| 集成 | 手动 dogfood + E2E 注册表 | Wave 1/2 验收清单 |

参考 LA 测试（移植为 unit，不直接依赖 LA 代码）：

- `test_chunker_unified.py`
- `test_summarize_segment.py`
- `test_segment_prefetch.py`
- `test_web_search.py`

---

## 12. 明确不引入（v1.0）

| 技术 | 原因 |
|------|------|
| LangGraph / LangChain Agent | 非 Agent 产品 |
| Mem0 / Chroma / BM25 重栈 | 跨书 v1.0 用 FTS5 足够 |
| Electron / Tauri | mac 要求 SwiftUI 原生体验；Windows 选用 WinUI 3，同样不引入 Web 壳 |
| deep-translator | 翻译走 LLM |
| LocalAgent 代码依赖 | 独立产品；仅参考算法 |

---

## 13. 开放项（v1.0 仍待定）

| 项 | 状态 | 下一步 |
|----|------|--------|
| Sidecar 打包 | 待定 | PyInstaller vs uv embedded — Wave 1 spike |
| SSE vs WebSocket | ✅ | SSE |
| DB 写入方 | ✅ | Core 独占写 |
| sqlite-vec | 待定 | FTS 先行，vec v1.1 |
| 全书视图 | 待定 | v1.1 与产品方设计 |
| 预置 RSS URL 清单 | 待定 | 产品确认 |
| 证据充分性实现 | 待定 | Spike：LLM self-check vs 召回分数阈值 |
| segment 缓存 2GB 默认 | ✅ 暂定 | 可配置；Spike 验证 |
| 笔记划线 offset | 待定 | EPUB 重排风险；v1.0 存 quote 文本 |
| Sidecar 崩溃恢复 | 待定 | job 状态 SQLite 持久化 |

---

## 14. 用户故事 → 技术决策映射

> 已拍板项见 §0；本节为最终结论归档。

### B1 批量导入

| 决策 | 状态 | 结论 |
|------|------|------|
| 文件存储 | ✅ | **复制**到 App Support |
| 重复导入 | ✅ | 同 `file_hash` → 409 + 用户确认**覆盖**；批量可跳过剩下所有重复、仍导入新书 |
| 批量队列 | ✅ | 10+ 本可同时提交；CPU 队列默认并发 1 |
| EPUB 解析库 | ✅ | **`ebooklib` 为核心**自建 pipeline |
| 超大文件 | ✅ | **>500MB 警告并拒绝** |

### B2 / B11 分段与 prefetch

| 决策 | 状态 | 结论 |
|------|------|------|
| 短书不切段 | ✅ | ≤12000 字整本一段 |
| 分段时机 | ✅ | **导入即开始**分段+摘要 |
| 段生成失败 | ✅ | 重试 **3 次** → `failed`；可手动 retry |
| 磁盘缓存上限 | ✅ | 单书 **2GB** quota；LRU 淘汰 |

### B12 听文本

| 决策 | 状态 | 结论 |
|------|------|------|
| 朗读稿 | ✅ | Python `build_listen_script` 为真源；简要=sentences；完整=总结+要点，不含 notes / follow_ups |
| 引擎 | ✅ | 仅系统离线语音包（macOS Premium/增强，Windows Neural）；设置引导系统下载页，不代下、不接云端 TTS |
| 摘要听读 | ✅ | 只走 summary 列 / `GET .../summary`，禁止为听简要/完整摘要拉 `raw_text` |
| 离开即停 | ✅ | 切书 / 离开阅读器取消合成 |

### B3 自动翻译

| 决策 | 状态 | 结论 |
|------|------|------|
| v1 翻译策略 | ✅ | **自动 LLM**；用户无感知 |
| 古文 | ✅ | v1 **不单独处理** |
| GPU 争抢 | ✅ | 摘要 > 翻译；深聊最高 |

### B4 / B5 深聊 + 联网

| 决策 | 状态 | 结论 |
|------|------|------|
| 对话线程 | ✅ | 每书一个 thread |
| 联网触发 | ✅ | **证据充分性驱动**（非关键词） |
| Token 预算 | ✅ | **分层索引 + DCA** |
| Citation | ✅ | **JSON mode** |
| 流式协议 | ✅ | SSE |

### B6 / B7 溯源与选区

| 决策 | 状态 | 结论 |
|------|------|------|
| 段级跳转 | ✅ | citation → segment index |
| 段内高亮 | ✅ | v1.0 **整段闪高亮** |
| 跨段选区 | ✅ | v1.0 截断至单段 |

### B8 笔记与跨书 recall

| 决策 | 状态 | 结论 |
|------|------|------|
| v1.0 检索 | ✅ | FTS5 |
| 笔记索引 | ✅ | 写入即 FTS trigger |
| 必须挂段 | ✅ | `segment_id` NOT NULL；创建校验归属 |
| 书内 / 应用级列表 | ✅ | NotesPanel 当前段\|全部 + 书库全部笔记跨书；点击跳段 |

### B9 导出

| 决策 | 状态 | 结论 |
|------|------|------|
| 格式 | ✅ | Markdown only |
| 含译文 | ✅ | **默认含译文**（`mode=full`） |
| 含笔记 | ✅ | 完整版可选勾选 |
| 仅总结 | ✅ | `mode=sentences`：只要各段三句话，无要点/注意/追问/译文/笔记 |

### B10 Ollama / 模型

| 决策 | 状态 | 结论 |
|------|------|------|
| 模型档位 | ✅ | RAM 分档 qwen3.5 |
| 三套配置 | ✅ | chat / summarize / translate 分开 |
| chat 推荐 | ✅ | **外部 API**；摘要/翻译 Ollama |
| Ollama 引导 | ✅ | 参考 LA `ollama_setup.py` |
| Job 抢占 | ✅ | **仅书库深聊**暂停书库 prefetch；资讯精读/深聊/sync **不** pause 书库队列，两边可并行 |

### N1–N4 资讯 lite

| 决策 | 状态 | 结论 |
|------|------|------|
| 简报摘要 | ✅ | **标题 + RSS excerpt 规则截取** |
| 精读复用 | ✅ | 临时 segment + Chat 组件 |

### 横切

| 决策 | 状态 | 结论 |
|------|------|------|
| API Key | ✅ | `secrets.json` → core 启动加载；Swift 经 HTTP 读写 |
| telemetry | ✅ | v1.0 无 |

---

## 附录 A：LocalAgent → Lumina 模块映射

| LA 模块 | Lumina 模块 | 迁移方式 |
|---------|-------------|----------|
| `ingest/ocr.py` | `lumina_core/ingest/ocr.py` | 重写；**保留 PP-OCRv6 + PyMuPDF 流程** |
| `summarize/segment_reader.py` | `lumina_core/summarize/` | 重写；+ label 字段 |
| `summarize/segment_prefetch.py` | `lumina_core/jobs/prefetch.py` | 重写；asyncio |
| `summarize/segment_cache.py` | SQLite `segments` 表 | 替代 JSON 文件 |
| `summarize/translate.py` | `lumina_core/translate/` | 改为 LLM 翻译 |
| `tools/web_search.py` | `lumina_core/search/web.py` | 抽取 subset |
| `news/sync+rank+brief` | `lumina_core/news/` | 重写；去 schedule |
| `models/router.py` | `lumina_core/models/router.py` | 重写；httpx only |

## 附录 B：首个 Spike 清单

1. `lumina-core`：`POST /books/import` TXT → chunk → summarize segment 0
2. Ollama 流式 `POST /books/{id}/chat`
3. SwiftUI 最小 Reader：段列表 + 摘要 + 输入框
4. 验证首段 ≤15s（Ollama 4b · 16GB）
