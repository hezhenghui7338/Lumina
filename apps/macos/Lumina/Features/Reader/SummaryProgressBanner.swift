import SwiftUI

/// Book-level summary progress: ready/total label, thin bar, optional active-segment caption.
struct SummaryProgressBanner: View {
    let readyCount: Int
    let totalCount: Int
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
