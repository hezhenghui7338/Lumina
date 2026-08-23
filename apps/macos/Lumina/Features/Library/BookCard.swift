import SwiftUI

struct BookCard: View {
    let book: BookSummary
    let isClassifying: Bool
    var ingestProgress: IngestProgress?
    var isSelectionMode: Bool = false
    var isChecked: Bool = false
    var onToggleCheck: (() -> Void)? = nil
    let onOpen: () -> Void
    let onToggleFavorite: () -> Void
    let onReclassify: () -> Void
    let onExport: () -> Void
    let onDelete: () -> Void
    var onStartSummarize: ((SummaryTier) -> Void)? = nil
    var onStopSummarize: (() -> Void)? = nil

    var body: some View {
        Button(action: handleTap) {
            VStack(alignment: .leading, spacing: 8) {
                ZStack(alignment: .topTrailing) {
                    cover
                    if isSelectionMode {
                        Image(systemName: isChecked ? "checkmark.circle.fill" : "circle")
                            .font(.title3)
                            .foregroundStyle(isChecked ? LuminaTheme.accent : .white.opacity(0.9))
                            .padding(8)
                    } else if book.isFavorite {
                        Image(systemName: "star.fill")
                            .font(.caption)
                            .foregroundStyle(.yellow)
                            .padding(8)
                    }
                }
                VStack(alignment: .leading, spacing: 4) {
                    Text(book.title)
                        .font(.headline)
                        .foregroundStyle(LuminaTheme.textPrimary)
                        .lineLimit(2)
                        .multilineTextAlignment(.leading)
                    Text(statusLine)
                        .font(.caption)
                        .foregroundStyle(LuminaTheme.textSecondary)
                        .lineLimit(2)
                    if book.isProcessing {
                        processingBar
                    } else if book.summaryTotal > 0, !book.hasCompletedSummary {
                        ProgressView(
                            value: Double(book.summaryReady),
                            total: Double(book.summaryTotal)
                        )
                        .controlSize(.small)
                        .tint(LuminaTheme.accent)
                    }
                    HStack(spacing: 6) {
                        Text(book.segmentCountLabel)
                        if let category = book.category, !category.isEmpty {
                            Text(category)
                        }
                    }
                    .font(.caption2)
                    .foregroundStyle(LuminaTheme.textSecondary)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .contextMenu { contextMenu }
    }

    private var statusLine: String {
        if book.isProcessing, let ingestProgress {
            return ingestProgress.label
        }
        if book.status == "error" {
            return book.statusLabel
        }
        if book.summaryTotal > 0, !book.hasCompletedSummary {
            return book.progressLabel
        }
        return book.readingStatusLabel
    }

    private var cover: some View {
        RoundedRectangle(cornerRadius: 8, style: .continuous)
            .fill(Self.coverColor(for: book.category))
            .aspectRatio(3 / 4, contentMode: .fit)
            .overlay {
                Text(book.coverInitial)
                    .font(.system(size: 36, weight: .semibold, design: .serif))
                    .foregroundStyle(.white.opacity(0.92))
            }
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .stroke(LuminaTheme.border, lineWidth: 1)
            )
    }

    @ViewBuilder
    private var processingBar: some View {
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
    }

    @ViewBuilder
    private var contextMenu: some View {
        Button(book.isFavorite ? "取消收藏" : "收藏", action: onToggleFavorite)
        Button("重新分类", action: onReclassify)
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
        Button("导出 Markdown 摘要…", action: onExport)
            .disabled(book.summaryReady == 0)
        Divider()
        Button("删除", role: .destructive, action: onDelete)
    }

    private func handleTap() {
        if isSelectionMode {
            onToggleCheck?()
        } else {
            onOpen()
        }
    }

    static func coverColor(for category: String?) -> Color {
        switch category {
        case "文学": return Color(red: 0.72, green: 0.38, blue: 0.32)
        case "历史": return Color(red: 0.55, green: 0.42, blue: 0.28)
        case "科技": return Color(red: 0.28, green: 0.45, blue: 0.62)
        case "哲学": return Color(red: 0.42, green: 0.36, blue: 0.58)
        case "经济": return Color(red: 0.28, green: 0.52, blue: 0.42)
        case "传记": return Color(red: 0.62, green: 0.42, blue: 0.28)
        default: return Color(red: 0.45, green: 0.46, blue: 0.50)
        }
    }
}
