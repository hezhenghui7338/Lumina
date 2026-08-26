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
    let onRename: () -> Void
    let onReclassify: () -> Void
    let onResegment: () -> Void
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
                    if book.isSegmenting {
                        LibraryIngestMeter(progress: ingestProgress)
                    } else if book.summaryTotal > 0, !book.hasCompletedSummary {
                        LibraryIngestMeter(
                            fraction: Double(book.summaryReady) / Double(book.summaryTotal)
                        )
                    }
                    HStack(spacing: 6) {
                        BookSummaryStateBadge(book: book)
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
        if book.isSegmenting {
            return ingestProgress?.label ?? book.summaryFacetLabel
        }
        if book.isIngestFailed {
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
            .overlay(alignment: .leading) {
                Rectangle()
                    .fill(.black.opacity(0.18))
                    .frame(width: 3)
            }
            .overlay {
                coverTypography
                    .padding(EdgeInsets(top: 12, leading: 14, bottom: 12, trailing: 12))
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                    .accessibilityHidden(true)
            }
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .stroke(LuminaTheme.border, lineWidth: 1)
            )
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }

    private var coverTypography: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(book.title)
                .font(.system(size: 17, weight: .semibold, design: .serif))
                .foregroundStyle(.white.opacity(0.95))
                .multilineTextAlignment(.leading)
                .lineLimit(5)
                .minimumScaleFactor(0.75)
                .frame(maxWidth: .infinity, alignment: .leading)
            Spacer(minLength: 0)
            if let author = book.author?.trimmingCharacters(in: .whitespacesAndNewlines),
               !author.isEmpty {
                Text(author)
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(.white.opacity(0.82))
                    .lineLimit(2)
            }
        }
    }

    @ViewBuilder
    private var contextMenu: some View {
        bookLibraryContextMenu(
            book: book,
            onToggleFavorite: onToggleFavorite,
            onRename: onRename,
            onReclassify: onReclassify,
            onResegment: onResegment,
            onExport: onExport,
            onDelete: onDelete,
            onStartSummarize: onStartSummarize,
            onStopSummarize: onStopSummarize
        )
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

/// Determinate meter only. A spinning progress indicator on macOS
/// (NSProgressIndicator) can steal clicks from other bookshelf cards.
struct LibraryIngestMeter: View {
    var fraction: Double
    var dimmed: Bool

    init(progress: IngestProgress?) {
        let total = progress?.total ?? 0
        if total > 0, let page = progress?.page {
            fraction = min(1, max(0, Double(page) / Double(total)))
            dimmed = false
        } else {
            fraction = 0
            dimmed = true
        }
    }

    init(fraction: Double) {
        self.fraction = min(1, max(0, fraction))
        dimmed = false
    }

    var body: some View {
        ProgressView(value: fraction)
            .controlSize(.small)
            .tint(LuminaTheme.accent)
            .opacity(dimmed ? 0.45 : 1)
    }
}
