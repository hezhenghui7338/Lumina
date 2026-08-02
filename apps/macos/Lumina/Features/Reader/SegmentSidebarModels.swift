import SwiftUI

// MARK: - Models

struct SidebarSegmentItem: Identifiable, Equatable {
    let id: String
    let idx: Int
    let chapterTitle: String
    let outlineLabel: String?
    let bulletPreview: String?
    let summaryStatus: String

    static func make(
        from segment: SegmentRow,
        bulletPreview: String?,
        runningMetrics: SegmentRunningMetrics?
    ) -> SidebarSegmentItem {
        let chapterTitle: String
        if let chapter = segment.chapter, !chapter.isEmpty {
            chapterTitle = chapter
        } else {
            chapterTitle = "段 \(segment.idx + 1)"
        }

        let outlineLabel: String?
        if let label = segment.label, !label.isEmpty {
            outlineLabel = label
        } else {
            switch segment.summary_status {
            case "running":
                outlineLabel = runningMetrics.map {
                    SummaryMetricsFormatter.inProgressLabel(
                        startedAt: $0.startedAt,
                        llmAttempt: $0.llmAttempt,
                        maxLlmAttempts: $0.maxLlmAttempts,
                        now: Date()
                    )
                } ?? "摘要生成中…"
            case "pending":
                outlineLabel = "等待摘要…"
            case "failed", "error":
                outlineLabel = SummaryMetricsFormatter.failureLabel(
                    durationS: segment.summary_duration_s,
                    retryCount: segment.retry_count
                )
            default:
                outlineLabel = nil
            }
        }

        let preview: String?
        if segment.label != nil && !(segment.label?.isEmpty ?? true) {
            preview = nil
        } else {
            preview = bulletPreview
        }

        return SidebarSegmentItem(
            id: segment.id,
            idx: segment.idx,
            chapterTitle: chapterTitle,
            outlineLabel: outlineLabel,
            bulletPreview: preview,
            summaryStatus: segment.summary_status
        )
    }
}

struct IndexedWindow<Item> {
    let items: [Item]
    let aboveCount: Int
    let belowCount: Int
    let startIndex: Int
    let totalCount: Int

    var isEmpty: Bool { totalCount == 0 }
}

enum SegmentRenderWindow {
    static let scrollAnimateThreshold = 15
    /// 主阅读区摘要/原文 prefetch 半径（段数）
    static let readBuffer = 4

    static func slice<Item>(
        _ all: [Item],
        centerIndex: Int,
        buffer: Int
    ) -> IndexedWindow<Item> {
        guard !all.isEmpty else {
            return IndexedWindow(
                items: [],
                aboveCount: 0,
                belowCount: 0,
                startIndex: 0,
                totalCount: 0
            )
        }
        let clampedCenter = min(max(0, centerIndex), all.count - 1)
        let start = max(0, clampedCenter - buffer)
        let end = min(all.count - 1, clampedCenter + buffer)
        return IndexedWindow(
            items: Array(all[start...end]),
            aboveCount: start,
            belowCount: all.count - 1 - end,
            startIndex: start,
            totalCount: all.count
        )
    }

    static func centerIndex(forSegmentIdx idx: Int, in segments: [SegmentRow]) -> Int {
        segments.firstIndex(where: { $0.idx == idx }) ?? 0
    }

    static func segmentIndexDelta(from currentIdx: Int?, to targetIdx: Int, in segments: [SegmentRow]) -> Int {
        guard let currentIdx,
              let from = segments.firstIndex(where: { $0.idx == currentIdx }),
              let to = segments.firstIndex(where: { $0.idx == targetIdx })
        else {
            return Int.max
        }
        return abs(to - from)
    }
}

// MARK: - Row View

struct SegmentSidebarRowView: View, Equatable {
    let item: SidebarSegmentItem
    let isSelected: Bool
    let showsLiveProgress: Bool
    let runningMetrics: SegmentRunningMetrics?

    static func == (lhs: SegmentSidebarRowView, rhs: SegmentSidebarRowView) -> Bool {
        lhs.item == rhs.item
            && lhs.isSelected == rhs.isSelected
            && lhs.showsLiveProgress == rhs.showsLiveProgress
            && lhs.runningMetrics == rhs.runningMetrics
    }

    var body: some View {
        HStack(alignment: .top, spacing: 6) {
            statusIcon
            VStack(alignment: .leading, spacing: 2) {
                Text(item.chapterTitle)
                    .font(.subheadline)
                    .lineLimit(1)
                if let outline = item.outlineLabel {
                    if showsLiveProgress, runningMetrics != nil {
                        TimelineView(.periodic(from: .now, by: 1)) { context in
                            Text(progressLabel(at: context.date))
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .lineLimit(2)
                        }
                    } else {
                        Text(outline)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                    }
                }
                if let preview = item.bulletPreview {
                    Text(preview)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
        }
        .padding(.vertical, 6)
        .padding(.horizontal, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            isSelected
                ? LuminaTheme.listSelectionBackground
                : Color.clear
        )
    }

    @ViewBuilder
    private var statusIcon: some View {
        if isSelected {
            Image(systemName: "largecircle.fill.circle")
                .foregroundStyle(LuminaTheme.accent)
        } else {
            switch item.summaryStatus {
            case "ready":
                Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
            case "running":
                Image(systemName: "circle.lefthalf.filled").foregroundStyle(LuminaTheme.accent)
            case "failed", "error":
                Image(systemName: "exclamationmark.circle").foregroundStyle(.red)
            default:
                Image(systemName: "circle").foregroundStyle(.secondary)
            }
        }
    }

    private func progressLabel(at now: Date) -> String {
        guard let runningMetrics else { return "摘要生成中…" }
        return SummaryMetricsFormatter.inProgressLabel(
            startedAt: runningMetrics.startedAt,
            llmAttempt: runningMetrics.llmAttempt,
            maxLlmAttempts: runningMetrics.maxLlmAttempts,
            now: now
        )
    }
}
