import SwiftUI

/// When the reading surface should show book/library summarize progress.
enum ReaderSummaryProgressPolicy {
    static func shouldShowContentBanner(
        readyCount: Int,
        totalCount: Int,
        overviewActive: Bool,
        segmentListVisible: Bool
    ) -> Bool {
        guard !segmentListVisible else { return false }
        let bookIncomplete = totalCount > 0 && readyCount < totalCount
        return bookIncomplete || overviewActive
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

/// Book-level summary progress: ready/total label, thin bar, optional queue + active-segment captions.
struct SummaryProgressBanner: View {
    let readyCount: Int
    let totalCount: Int
    var activityLabel: String? = nil
    var activeLabelProvider: ((Date) -> String?)?
    /// When false, show even when all segments are ready (e.g. sidebar header).
    var hideWhenComplete: Bool = true

    var body: some View {
        if totalCount > 0, !hideWhenComplete || readyCount < totalCount {
            VStack(alignment: .leading, spacing: 4) {
                Text("摘要 \(readyCount)/\(totalCount)")
                    .font(.caption)
                    .foregroundStyle(LuminaTheme.textSecondary)

                ProgressView(
                    value: Double(readyCount),
                    total: Double(totalCount)
                )
                .controlSize(.small)
                .tint(LuminaTheme.accent)

                if let activityLabel, !activityLabel.isEmpty {
                    Text(activityLabel)
                        .font(.caption)
                        .foregroundStyle(LuminaTheme.textSecondary)
                        .lineLimit(1)
                }

                if activeLabelProvider != nil {
                    TimelineView(.periodic(from: .now, by: 1)) { context in
                        if let label = activeLabelProvider?(context.date), !label.isEmpty {
                            Text(label)
                                .font(.caption2)
                                .foregroundStyle(LuminaTheme.textSecondary)
                                .lineLimit(1)
                        }
                    }
                }
            }
        }
    }
}
