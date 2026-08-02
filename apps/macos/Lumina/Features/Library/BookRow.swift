import SwiftUI

struct BookRow: View {
    let book: BookSummary
    let isClassifying: Bool
    var ingestProgress: IngestProgress?
    var isSelectionMode: Bool = false
    var isChecked: Bool = false
    var onToggleCheck: (() -> Void)? = nil
    let onToggleFavorite: () -> Void
    let onReclassify: () -> Void
    let onExport: () -> Void
    let onDelete: () -> Void
    var onStartSummarize: (() -> Void)? = nil
    var onStopSummarize: (() -> Void)? = nil

    private var statusText: String {
        if book.isProcessing, let ingestProgress {
            return ingestProgress.label
        }
        return summarizeStatusLabel
    }

    private var summarizeStatusLabel: String {
        let total = book.summaryTotal
        if total <= 0 { return book.statusLabel }
        let ready = book.summaryReady
        if ready >= total { return "已摘要" }

        switch book.summarize_state {
        case "running":
            var label = "正在摘要 · \(ready)/\(total)"
            if let active = book.summarize_active,
               let activeLabel = SummaryMetricsFormatter.bookActiveLabel(active: active) {
                label += " · \(activeLabel)"
            }
            return label
        case "queued":
            if book.summarizeQueuedCount > 0 {
                return "排队中 · 摘要 \(ready)/\(total) · \(book.summarizeQueuedCount) 段待处理"
            }
            return "排队中 · 摘要 \(ready)/\(total)"
        case "paused":
            return "已暂停 · 摘要 \(ready)/\(total)"
        case "idle":
            return "待摘要 · \(ready)/\(total)"
        default:
            return book.progressLabel
        }
    }

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            if isSelectionMode {
                Toggle(
                    isOn: Binding(
                        get: { isChecked },
                        set: { on in
                            if on != isChecked {
                                onToggleCheck?()
                            }
                        }
                    )
                ) {
                    EmptyView()
                }
                .toggleStyle(.checkbox)
                .labelsHidden()
            }

            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    if book.isFavorite {
                        Image(systemName: "star.fill")
                            .font(.caption)
                            .foregroundStyle(LuminaTheme.accent)
                    }
                    Text(book.title)
                        .font(.headline)
                        .foregroundStyle(LuminaTheme.textPrimary)
                        .lineLimit(2)
                }
                if book.summarize_state == "running" || book.summarize_active != nil {
                    TimelineView(.periodic(from: .now, by: 1)) { context in
                        Text(liveStatusText(at: context.date))
                            .font(.caption)
                            .foregroundStyle(LuminaTheme.textSecondary)
                    }
                } else {
                    Text(statusText)
                        .font(.caption)
                        .foregroundStyle(LuminaTheme.textSecondary)
                }
                if book.isProcessing {
                    if let ingestProgress, ingestProgress.total > 0 {
                        ProgressView(
                            value: Double(ingestProgress.page),
                            total: Double(ingestProgress.total)
                        )
                        .controlSize(.small)
                        .tint(LuminaTheme.accent)
                    } else {
                        ProgressView()
                            .controlSize(.small)
                            .tint(LuminaTheme.accent)
                    }
                } else if book.summaryTotal > 0 {
                    if book.summarize_state == "queued" {
                        ProgressView()
                            .controlSize(.small)
                            .tint(LuminaTheme.accent)
                    } else {
                        ProgressView(
                            value: Double(book.summaryReady),
                            total: Double(book.summaryTotal)
                        )
                        .controlSize(.small)
                        .tint(LuminaTheme.accent)
                    }
                }
                HStack(spacing: 6) {
                    summarizeStateBadge
                    categoryBadge
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.vertical, 2)
        .frame(maxWidth: .infinity, alignment: .leading)
        .contextMenu {
            Button(book.isFavorite ? "取消收藏" : "收藏") {
                onToggleFavorite()
            }
            Button("重新分类") {
                onReclassify()
            }
            if book.canStartSummarize, let onStartSummarize {
                Button("开始摘要") {
                    onStartSummarize()
                }
            }
            if book.canStopSummarize, let onStopSummarize {
                Button("停止摘要") {
                    onStopSummarize()
                }
            }
            Button("导出 Markdown 摘要…") {
                onExport()
            }
            .disabled(book.summaryReady == 0)
            Divider()
            Button("删除", role: .destructive) {
                onDelete()
            }
        }
    }

    private func liveStatusText(at now: Date) -> String {
        let total = book.summaryTotal
        guard total > 0 else { return book.statusLabel }
        let ready = book.summaryReady
        if ready >= total { return "已摘要" }
        var label = "正在摘要 · \(ready)/\(total)"
        if let active = book.summarize_active,
           let activeLabel = SummaryMetricsFormatter.bookActiveLabel(active: active, now: now) {
            label += " · \(activeLabel)"
        }
        return label
    }

    @ViewBuilder
    private var summarizeStateBadge: some View {
        switch book.summarize_state {
        case "running":
            Text("正在摘要")
                .font(.caption2)
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .background(LuminaTheme.accentMuted)
                .foregroundStyle(LuminaTheme.accent)
                .clipShape(Capsule())
        case "queued":
            Text("排队中")
                .font(.caption2)
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .background(LuminaTheme.border.opacity(0.45))
                .foregroundStyle(LuminaTheme.textSecondary)
                .clipShape(Capsule())
        case "paused":
            Text("已暂停")
                .font(.caption2)
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .background(Color.orange.opacity(0.15))
                .foregroundStyle(.orange)
                .clipShape(Capsule())
        case "idle":
            Text("待摘要")
                .font(.caption2)
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .background(LuminaTheme.border.opacity(0.35))
                .foregroundStyle(LuminaTheme.textSecondary)
                .clipShape(Capsule())
        default:
            EmptyView()
        }
    }

    @ViewBuilder
    private var categoryBadge: some View {
        if isClassifying {
            Text("分类中…")
                .font(.caption2)
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .background(LuminaTheme.accentMuted)
                .foregroundStyle(LuminaTheme.accent)
                .clipShape(Capsule())
        } else if let category = book.category, !category.isEmpty {
            Text(category)
                .font(.caption2)
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .background(LuminaTheme.border.opacity(0.45))
                .foregroundStyle(LuminaTheme.textSecondary)
                .clipShape(Capsule())
        }
    }
}
