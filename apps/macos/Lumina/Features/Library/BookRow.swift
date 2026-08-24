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
    let onResegment: () -> Void
    let onExport: () -> Void
    let onDelete: () -> Void
    var onStartSummarize: ((SummaryTier) -> Void)? = nil
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
        if ready >= total { return book.readingStatusLabel }

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
                } else if book.summaryTotal > 0, !book.hasCompletedSummary {
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
                    if let count = book.segment_count, count > 0 {
                        Text("\(count) 段")
                            .font(.caption2)
                            .foregroundStyle(LuminaTheme.textSecondary)
                    }
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.vertical, 2)
        .frame(maxWidth: .infinity, alignment: .leading)
        .contextMenu {
            bookLibraryContextMenu(
                book: book,
                onToggleFavorite: onToggleFavorite,
                onReclassify: onReclassify,
                onResegment: onResegment,
                onExport: onExport,
                onDelete: onDelete,
                onStartSummarize: onStartSummarize,
                onStopSummarize: onStopSummarize
            )
        }
    }

    private func liveStatusText(at now: Date) -> String {
        let total = book.summaryTotal
        guard total > 0 else { return book.statusLabel }
        let ready = book.summaryReady
        if ready >= total { return book.readingStatusLabel }
        var label = "正在摘要 · \(ready)/\(total)"
        if let active = book.summarize_active,
           let activeLabel = SummaryMetricsFormatter.bookActiveLabel(active: active, now: now) {
            label += " · \(activeLabel)"
        }
        return label
    }

    @ViewBuilder
    private var summarizeStateBadge: some View {
        if book.hasCompletedSummary {
            Text("已摘要")
                .font(.caption2)
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .background(LuminaTheme.border.opacity(0.45))
                .foregroundStyle(LuminaTheme.textSecondary)
                .clipShape(Capsule())
        } else {
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

@ViewBuilder
func bookLibraryContextMenu(
    book: BookSummary,
    onToggleFavorite: @escaping () -> Void,
    onReclassify: @escaping () -> Void,
    onResegment: @escaping () -> Void,
    onExport: @escaping () -> Void,
    onDelete: @escaping () -> Void,
    onStartSummarize: ((SummaryTier) -> Void)? = nil,
    onStopSummarize: (() -> Void)? = nil
) -> some View {
    Button(book.isFavorite ? "取消收藏" : "收藏", action: onToggleFavorite)
    Button("重新分类", action: onReclassify)
        .disabled(!LibraryBookContextMenuPolicy.isEnabled(.reclassify, for: book))
    if book.canStartSummarize, let onStartSummarize {
        Menu("开始摘要") {
            ForEach(SummaryTier.allCases) { tier in
                Button(tier.startMenuLabel) { onStartSummarize(tier) }
            }
        }
    }
    if book.canStopSummarize, let onStopSummarize {
        Button("停止摘要", action: onStopSummarize)
    }
    Button("整书重新分段", action: onResegment)
        .disabled(!LibraryBookContextMenuPolicy.isEnabled(.resegment, for: book))
    Button("导出 Markdown 摘要…", action: onExport)
        .disabled(!LibraryBookContextMenuPolicy.isEnabled(.exportMarkdown, for: book))
    Divider()
    Button("删除", role: .destructive, action: onDelete)
}
