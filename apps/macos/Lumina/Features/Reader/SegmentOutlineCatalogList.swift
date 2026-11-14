import SwiftUI

/// Segment-list scroll body. Takes a cached outline snapshot so summarize
/// progress ticks (`segmentRunningMetrics`) do not re-run `SegmentOutlinePolicy.build`.
struct SegmentOutlineCatalogList: View, Equatable {
    let rows: [SegmentOutlinePolicy.Row]
    var introStatus: String? = nil
    let selectedIdx: Int?
    let isSelectionMode: Bool
    let checkedIndices: Set<Int>
    let segmentSwitchDuration: TimeInterval
    var onRevealSelection: (Int?) -> Void
    var onToggleOutlineKey: (String) -> Void
    var onSelect: (Int) -> Void
    var onToggleCheck: (Int) -> Void
    var onRetrySegment: (Int) -> Void
    var onRetryChecked: () -> Void
    var canGenerateSummary: Bool = true

    static func == (lhs: SegmentOutlineCatalogList, rhs: SegmentOutlineCatalogList) -> Bool {
        lhs.rows == rhs.rows
            && lhs.canGenerateSummary == rhs.canGenerateSummary
            && lhs.introStatus == rhs.introStatus
            && lhs.selectedIdx == rhs.selectedIdx
            && lhs.isSelectionMode == rhs.isSelectionMode
            && lhs.checkedIndices == rhs.checkedIndices
            && lhs.segmentSwitchDuration == rhs.segmentSwitchDuration
    }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    if let introStatus {
                        Button { onSelect(BookReadingItem.introIndex) } label: {
                            HStack(spacing: 8) {
                                Image(systemName: selectedIdx == BookReadingItem.introIndex
                                    ? "largecircle.fill.circle" : "sparkles")
                                    .foregroundStyle(LuminaTheme.accent)
                                    .frame(width: 20)
                                Text("AI 导读")
                                Spacer()
                                Text(introStatus == "pending" ? "生成中" : (introStatus == "ready" ? "" : "待获取"))
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            .padding(.horizontal, 12)
                            .padding(.vertical, 8)
                            .contentShape(Rectangle())
                            .background(selectedIdx == BookReadingItem.introIndex
                                ? LuminaTheme.listSelectionBackground : Color.clear)
                        }
                        .buttonStyle(.plain)
                        .id("s:\(BookReadingItem.introIndex)")
                        .accessibilityIdentifier("lumina.reader.catalog.intro")
                    }
                    ForEach(rows) { row in
                        outlineCatalogRow(row)
                            .id(row.id)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .frame(maxWidth: .infinity)
            }
            .onChange(of: selectedIdx) { _, idx in
                guard let idx else { return }
                onRevealSelection(idx)
                withAnimation(.easeInOut(duration: segmentSwitchDuration)) {
                    proxy.scrollTo("s:\(idx)", anchor: .center)
                }
            }
            .onAppear {
                onRevealSelection(selectedIdx)
                guard let idx = selectedIdx else { return }
                Task { @MainActor in
                    await Task.yield()
                    proxy.scrollTo("s:\(idx)", anchor: .center)
                }
            }
        }
    }

    @ViewBuilder
    private func outlineCatalogRow(_ row: SegmentOutlinePolicy.Row) -> some View {
        if row.isHeader {
            outlineHeaderRow(row)
        } else if let seg = row.segment {
            SegmentOutlineCatalogLeafRow(
                segment: seg,
                grouped: row.grouped,
                depth: row.depth,
                isSelected: selectedIdx == seg.idx,
                isSelectionMode: isSelectionMode,
                isChecked: checkedIndices.contains(seg.idx),
                checkedCount: checkedIndices.count,
                onSelect: onSelect,
                onToggleCheck: onToggleCheck,
                onRetrySegment: onRetrySegment,
                onRetryChecked: onRetryChecked,
                canGenerateSummary: canGenerateSummary
            )
            .equatable()
        }
    }

    private func outlineHeaderRow(_ row: SegmentOutlinePolicy.Row) -> some View {
        Button {
            onToggleOutlineKey(row.pathKey)
        } label: {
            HStack(spacing: 6) {
                Image(systemName: row.isCollapsed ? "chevron.right" : "chevron.down")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .frame(width: 12)
                Text(row.title)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.tail)
                Text("\(row.headerCount)")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .padding(.leading, CGFloat(row.depth) * SegmentOutlinePolicy.indentStep)
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

private struct SegmentOutlineCatalogLeafRow: View, Equatable {
    let segment: SegmentRow
    let grouped: Bool
    let depth: Int
    let isSelected: Bool
    let isSelectionMode: Bool
    let isChecked: Bool
    let checkedCount: Int
    var onSelect: (Int) -> Void
    var onToggleCheck: (Int) -> Void
    var onRetrySegment: (Int) -> Void
    var onRetryChecked: () -> Void
    var canGenerateSummary: Bool = true

    static func == (lhs: SegmentOutlineCatalogLeafRow, rhs: SegmentOutlineCatalogLeafRow) -> Bool {
        lhs.segment == rhs.segment
            && lhs.canGenerateSummary == rhs.canGenerateSummary
            && lhs.grouped == rhs.grouped
            && lhs.depth == rhs.depth
            && lhs.isSelected == rhs.isSelected
            && lhs.isSelectionMode == rhs.isSelectionMode
            && lhs.isChecked == rhs.isChecked
            && lhs.checkedCount == rhs.checkedCount
    }

    var body: some View {
        let rowContent = HStack(alignment: .top, spacing: 8) {
            if isSelectionMode {
                Toggle(
                    isOn: Binding(
                        get: { isChecked },
                        set: { on in
                            if on != isChecked {
                                onToggleCheck(segment.idx)
                            }
                        }
                    )
                ) {
                    EmptyView()
                }
                .toggleStyle(.checkbox)
                .labelsHidden()
            }

            statusIcon
            SegmentSidebarRow(segment: segment, grouped: grouped)
        }
        .contentShape(Rectangle())
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            isSelected
                ? LuminaTheme.listSelectionBackground
                : Color.clear
        )
        .padding(.leading, CGFloat(depth) * SegmentOutlinePolicy.indentStep)

        Group {
            if isSelectionMode {
                rowContent
                    .onTapGesture { onToggleCheck(segment.idx) }
            } else {
                Button {
                    onSelect(segment.idx)
                } label: {
                    rowContent
                }
                .buttonStyle(.plain)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .contextMenu {
            if canGenerateSummary {
                if isChecked, checkedCount > 1 {
                    Button("重新摘要选中 (\(checkedCount))") {
                        onRetryChecked()
                    }
                } else {
                    Button("重新摘要") {
                        onRetrySegment(segment.idx)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private var statusIcon: some View {
        Group {
            if isSelected {
                Image(systemName: "largecircle.fill.circle")
                    .foregroundStyle(LuminaTheme.accent)
            } else {
                switch segment.summary_status {
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
        .font(.body)
        .frame(width: 20, alignment: .center)
    }
}
