import SwiftUI

struct SegmentSidebarView: View {
    let items: [SidebarSegmentItem]
    let selectedIdx: Int?
    let isSelectionMode: Bool
    let checkedIndices: Set<Int>
    let runningMetrics: [Int: SegmentRunningMetrics]
    let segmentSwitchDuration: TimeInterval
    var onSelect: (Int) -> Void
    var onToggleCheck: (Int) -> Void
    var onRetrySegment: (Int) -> Void
    var onRetryChecked: () -> Void

    @State private var scrollPosition: Int?

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 0) {
                ForEach(items) { item in
                    row(for: item)
                        .id(item.idx)
                }
            }
            .scrollTargetLayout()
        }
        .scrollPosition(id: $scrollPosition, anchor: .center)
        .onChange(of: selectedIdx) { _, idx in
            guard let idx, scrollPosition != idx else { return }
            Task { @MainActor in
                await Task.yield()
                let delta = indexDelta(from: scrollPosition ?? selectedIdx, to: idx)
                if delta <= SegmentRenderWindow.scrollAnimateThreshold {
                    withAnimation(.easeInOut(duration: segmentSwitchDuration)) {
                        scrollPosition = idx
                    }
                } else {
                    scrollPosition = idx
                }
            }
        }
        .onAppear {
            if scrollPosition == nil {
                scrollPosition = selectedIdx
            }
        }
    }

    @ViewBuilder
    private func row(for item: SidebarSegmentItem) -> some View {
        let isSelected = selectedIdx == item.idx
        let showsLiveProgress = isSelected && item.summaryStatus == "running"
        let rowContent = HStack(alignment: .top, spacing: 0) {
            if isSelectionMode {
                Toggle(
                    isOn: Binding(
                        get: { checkedIndices.contains(item.idx) },
                        set: { on in
                            let checked = checkedIndices.contains(item.idx)
                            if on != checked {
                                onToggleCheck(item.idx)
                            }
                        }
                    )
                ) {
                    EmptyView()
                }
                .toggleStyle(.checkbox)
                .labelsHidden()
                .padding(.trailing, 4)
            }

            SegmentSidebarRowView(
                item: item,
                isSelected: isSelected,
                showsLiveProgress: showsLiveProgress,
                runningMetrics: runningMetrics[item.idx]
            )
            .equatable()
        }
        .contentShape(Rectangle())

        Group {
            if isSelectionMode {
                rowContent
                    .onTapGesture { onToggleCheck(item.idx) }
            } else {
                Button {
                    onSelect(item.idx)
                } label: {
                    rowContent
                }
                .buttonStyle(.plain)
            }
        }
        .contextMenu {
            if checkedIndices.contains(item.idx), checkedIndices.count > 1 {
                Button("重新摘要选中 (\(checkedIndices.count))") {
                    onRetryChecked()
                }
            } else {
                Button("重新摘要") {
                    onRetrySegment(item.idx)
                }
            }
        }
    }

    private func indexDelta(from currentIdx: Int?, to targetIdx: Int) -> Int {
        guard let currentIdx,
              let from = items.firstIndex(where: { $0.idx == currentIdx }),
              let to = items.firstIndex(where: { $0.idx == targetIdx })
        else {
            return Int.max
        }
        return abs(to - from)
    }
}
