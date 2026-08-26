import SwiftUI

/// Outer height of the reader feed's summary-progress inset. Captions that are
/// missing still occupy their row so SSE ticks cannot steal feed height.
enum SummaryProgressBannerMetrics {
    static let rowSpacing: CGFloat = 4
    static let verticalPadding: CGFloat = 8
    static let titleLineHeight: CGFloat = 16
    static let barHeight: CGFloat = 8
    static let captionLineHeight: CGFloat = 16
    static let activeLineHeight: CGFloat = 14

    static var reservedHeight: CGFloat {
        verticalPadding * 2
            + titleLineHeight
            + rowSpacing
            + barHeight
            + rowSpacing
            + captionLineHeight
            + rowSpacing
            + activeLineHeight
    }
}

/// When the reading surface should show this book's summarize progress.
enum ReaderSummaryProgressPolicy {
    /// Feed banner is only for the open book while it is still incomplete.
    /// Hide it when the segment catalog is open (chrome already shows library
    /// activity) and when this book is fully summarized.
    static func shouldShowContentBanner(
        readyCount: Int,
        totalCount: Int,
        segmentListVisible: Bool
    ) -> Bool {
        guard !segmentListVisible else { return false }
        return totalCount > 0 && readyCount < totalCount
    }

    static func runningCount(in segments: [SegmentRow]) -> Int {
        segments.filter { $0.summary_status == "running" }.count
    }

    /// Remaining incomplete segments count as queued only after summarize has started.
    static func queuedCount(in segments: [SegmentRow], summarizeState: String?) -> Int {
        switch summarizeState {
        case "running", "queued":
            return segments.filter {
                switch $0.summary_status {
                case "pending", "error", "failed": return true
                default: return false
                }
            }.count
        default:
            return 0
        }
    }

    static func activityLabel(running: Int, queued: Int) -> String? {
        guard running > 0 || queued > 0 else { return nil }
        return SummarizeActivityChip.statusLabel(running: running, queued: queued)
    }
}

/// Book-level summary progress: ready/total label, thin bar, queue + active-segment captions.
/// Always four rows so appearing/disappearing captions cannot shift the feed.
struct SummaryProgressBanner: View {
    let readyCount: Int
    let totalCount: Int
    var activityLabel: String? = nil
    var activeLabelProvider: ((Date) -> String?)?

    var body: some View {
        VStack(alignment: .leading, spacing: SummaryProgressBannerMetrics.rowSpacing) {
            Text(titleText)
                .font(.caption)
                .foregroundStyle(LuminaTheme.textSecondary)
                .lineLimit(1)
                .minimumScaleFactor(0.8)
                .frame(height: SummaryProgressBannerMetrics.titleLineHeight, alignment: .leading)

            ProgressView(
                value: Double(readyCount),
                total: Double(max(totalCount, 1))
            )
            .controlSize(.small)
            .tint(LuminaTheme.accent)
            .frame(height: SummaryProgressBannerMetrics.barHeight)

            captionRow(
                text: activityLabel,
                font: .caption,
                lineHeight: SummaryProgressBannerMetrics.captionLineHeight
            )

            activeCaptionRow
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, SummaryProgressBannerMetrics.verticalPadding)
        .frame(height: SummaryProgressBannerMetrics.reservedHeight, alignment: .top)
    }

    private var titleText: String {
        "摘要 \(readyCount)/\(totalCount)"
    }

    @ViewBuilder
    private var activeCaptionRow: some View {
        Group {
            if let activeLabelProvider {
                TimelineView(.periodic(from: .now, by: 1)) { context in
                    captionRow(
                        text: activeLabelProvider(context.date),
                        font: .caption2,
                        lineHeight: SummaryProgressBannerMetrics.activeLineHeight
                    )
                }
            } else {
                captionRow(
                    text: nil,
                    font: .caption2,
                    lineHeight: SummaryProgressBannerMetrics.activeLineHeight
                )
            }
        }
        .frame(height: SummaryProgressBannerMetrics.activeLineHeight, alignment: .leading)
    }

    private func captionRow(text: String?, font: Font, lineHeight: CGFloat) -> some View {
        let shown = text?.isEmpty == false ? text : nil
        return Text(shown ?? " ")
            .font(font)
            .foregroundStyle(LuminaTheme.textSecondary)
            .lineLimit(1)
            .minimumScaleFactor(0.8)
            .opacity(shown == nil ? 0 : 1)
            .frame(height: lineHeight, alignment: .leading)
    }
}
