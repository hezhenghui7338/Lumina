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

    private var statusText: String {
        if book.isProcessing, let ingestProgress {
            return ingestProgress.label
        }
        return book.progressLabel
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
                        .lineLimit(2)
                }
                Text(statusText)
                    .font(.caption)
                    .foregroundStyle(LuminaTheme.textSecondary)
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
                    ProgressView(
                        value: Double(book.summaryReady),
                        total: Double(book.summaryTotal)
                    )
                    .controlSize(.small)
                    .tint(LuminaTheme.accent)
                }
                categoryBadge
            }
            Spacer(minLength: 0)
        }
        .padding(.vertical, 2)
        .contextMenu {
            Button(book.isFavorite ? "取消收藏" : "收藏") {
                onToggleFavorite()
            }
            Button("重新分类") {
                onReclassify()
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
