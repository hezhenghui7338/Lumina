# DesignSystem Snapshot 测试指南

**PRD 锚点**：[PRD §4.1 视觉方向](../PRD.md) · [§4.2 动效原则](../PRD.md)  
**主文档**：[testing.md](../testing.md)

---

## 1. 目标

v1.0 通过 **Snapshot 测试** 锁定 DesignSystem 视觉基线，确保：

- **浅色主题为默认**且回归可控
- 段列表、段内容、深聊区等核心阅读 UI 不因 refactor 意外漂移
- 段切换、citation 闪高等动效的**关键帧**有静态参照

Snapshot **不替代** XCUITest：动效时长（≤200ms）仍由 XCUITest `measure` 验证。

---

## 2. 工具

| 项 | 选择 |
|----|------|
| 库 | [swift-snapshot-testing](https://github.com/pointfreeco/swift-snapshot-testing)（Point-Free） |
| 集成 | Xcode SPM → `LuminaTests` target |
| 录制 | 环境变量 `LUMINA_RECORD_SNAPSHOTS=1` |
| 参考图路径 | `apps/macos/Lumina/LuminaTests/Snapshot/__Snapshots__/` |

```swift
// Package.swift 或 Xcode SPM
.package(url: "https://github.com/pointfreeco/swift-snapshot-testing", from: "1.17.0")
```

---

## 3. v1.0 覆盖清单

### 3.1 必拍 Snapshot（浅色）

| Snapshot 名 | 组件 | 说明 |
|-------------|------|------|
| `BookCard_light` | 书库卡片 | 封面 + 标题 + 进度条 |
| `BookCard_light_noCover` | 书库卡片 | 无封面 fallback |
| `SegmentListRow_states` | 段列表行 | ●当前 / ✓已读 / ◐生成中 / ○未生成 |
| `SegmentList_chapterGroup` | 章节分组 | 折叠/展开两态 |
| `SegmentContent_summary` | 段内容 | 三句话 + 要点 + 锚点 |
| `SegmentContent_originalOnly` | 段内容 | 仅原文（同语言书） |
| `SegmentContent_bilingual` | 段内容 | 原文+译文对照 |
| `ChatView_empty` | 深聊区 | 空态 + 输入框 |
| `ChatView_withCitations` | 深聊区 | 含 `[段 N]` 可点击链接 |
| `ChatView_withWebRefs` | 深聊区 | 含 `[网]` 标注 |
| `CitationLink_light` | Citation 链接 | 默认 / hover / pressed |
| `Reader_segmentSwitch_before` | 阅读器 | 段 A 选中态（animation off） |
| `Reader_segmentSwitch_after` | 阅读器 | 段 B 选中态（animation off） |
| `CitationFlash_highlight` | 段内容 | 整段闪高亮 peak 色 |
| `SegmentSkeleton_light` | 等待态 | skeleton shimmer 静态帧 |
| `SearchPalette_light` | ⌘K 浮层 | 有/无结果两态 |
| `Settings_themeToggle_light` | 设置 | 主题切换控件 |

### 3.2 v1.1 扩展

- 全组件 **暗色主题** Snapshot
- Onboarding 各步

---

## 4. 动效测试策略

PRD 要求段切换 ≤200ms crossfade、citation 闪高亮 ≤400ms — Snapshot 只捕获**关键帧**，不录动画中间过程。

| 动效 | Snapshot 方案 | 时长验证 |
|------|---------------|----------|
| 段切换 crossfade | 禁用 animation，拍段 A / 段 B 两帧 | XCUITest `measure` |
| Citation 闪高亮 | 拍 `.flashHighlight` peak 静态色 | — |
| skeleton shimmer | 拍静态 skeleton 组件（无动画） | — |
| 深聊滚底 | 不 snapshot | XCUITest 可选 |

### 4.1 测试模式禁用动画

```swift
extension View {
  func luminaTestMode() -> some View {
    self.transaction { transaction in
      transaction.animation = nil
    }
  }
}

// Snapshot 测试中
assertSnapshot(of: view.luminaTestMode(), as: .image(layout: .device(config: .mac)))
```

### 4.2 固定环境

```swift
// 固定字体、locale、尺寸，避免 CI 与本地差异
let config = ViewImageConfig.macDefault
  .with(size: CGSize(width: 1200, height: 800))
```

---

## 5. 编写 Snapshot 测试

```swift
import SnapshotTesting
import XCTest
@testable import Lumina

@MainActor
final class SegmentListSnapshotTests: XCTestCase {
  override func invokeTest() {
    withSnapshotTesting(record: .missing) {
      super.invokeTest()
    }
  }

  func testSegmentListRow_states() {
    let view = SegmentListRowPreview.statesPanel()
      .luminaTestMode()
      .frame(width: 280)

    assertSnapshot(of: view, as: .image, named: "light")
  }
}
```

**约定**：

- Preview 专用 struct 放在 `DesignSystem/Previews/` 或测试文件内
- 测试数据用 fixture，不依赖 sidecar / Ollama
- 每个 Snapshot 文件只测一个逻辑组件

---

## 6. 录制与更新

### 6.1 首次录制基线

```bash
LUMINA_RECORD_SNAPSHOTS=1 just test-snapshots

# 或 xcodebuild
LUMINA_RECORD_SNAPSHOTS=1 xcodebuild test \
  -scheme Lumina \
  -destination 'platform=macOS' \
  -only-testing:LuminaTests/SnapshotTests
```

`swift-snapshot-testing` 在 record 模式下会将参考图写入 `__Snapshots__/` 目录，**一并提交 git**。

### 6.2 有意更新 Snapshot

UI 改版经设计评审后：

1. 本地 `LUMINA_RECORD_SNAPSHOTS=1` 重录
2. PR 描述说明变更原因 + 附 before/after 截图
3. 审查 `__Snapshots__/` diff

### 6.3 失败排查

| 现象 | 可能原因 |
|------|----------|
| 字体渲染差异 | CI macOS 版本不同 → 固定 `ViewImageConfig` |
| 1px 抗锯齿差 | 提高 `precision` 或 `perceptualPrecision` |
| 动画中间帧 | 确认已 `.luminaTestMode()` |

```swift
assertSnapshot(of: view, as: .image(precision: 0.99))
```

---

## 7. CI 集成

`test-macos.yml` PR 必跑 Snapshot 测试。

失败时：

1. CI 上传 **diff 图** artifact
2. PR 状态失败，须更新 Snapshot 或修复回归

```yaml
# .github/workflows/test-macos.yml 片段
- name: Run Snapshot tests
  run: xcodebuild test -scheme Lumina -destination 'platform=macOS' \
       -only-testing:LuminaTests/SnapshotTests

- name: Upload snapshot diffs on failure
  if: failure()
  uses: actions/upload-artifact@v4
  with:
    name: snapshot-diffs
    path: apps/macos/Lumina/LuminaTests/Snapshot/__Snapshots__/
```

---

## 8. accessibilityIdentifier

Snapshot 不测交互；XCUITest 依赖 stable identifier。新增 UI 组件时同步添加：

```swift
Button("发送") { ... }
  .accessibilityIdentifier("chat.sendButton")
```

| 区域 | Identifier 示例 |
|------|-----------------|
| 段列表 | `segmentList.row.{index}` |
| 深聊输入 | `chat.inputField` |
| Citation | `citation.segment.{index}` |
| ⌘K 搜索 | `search.palette` |

完整列表维护在 `docs/testing/accessibility-ids.md`（实现阶段补充）。

---

## 9. PR Checklist（UI 变更）

- [ ] 是否改动 DesignSystem / 阅读器布局？
- [ ] 是 → 更新对应 Snapshot
- [ ] 新组件是否添加 Preview + Snapshot 测试？
- [ ] 新交互控件是否添加 `accessibilityIdentifier`？
- [ ] PR 是否附 Snapshot diff 说明？

---

## 10. 与 PRD §8.2 体验验收映射

| PRD 体验项 | 测试手段 |
|------------|----------|
| 浅色主题为默认 | Snapshot 基线全部为 light |
| 段切换无白屏 | Snapshot 两帧 + XCUITest |
| 深聊区常驻 | Snapshot `ChatView_*` |
| 长书无全屏 spinner | Snapshot `SegmentSkeleton_light` |
| 视觉评审 ≥4/5 | Snapshot 辅助；最终仍人工评审 |
