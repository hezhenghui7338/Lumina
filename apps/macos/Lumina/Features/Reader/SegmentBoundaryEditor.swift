import SwiftUI

struct SegmentBoundarySheet: View {
    let bookId: String
    let leftIdx: Int
    let core: CoreClient
    var onApplied: (SegmentBoundaryMoveResult, String, String) -> Void
    var onCancel: () -> Void

    @State private var concat = ""
    @State private var candidates: [SegmentBoundaryCandidate] = []
    @State private var candidateIndex = 0
    @State private var dragStartIndex = 0
    @State private var oversizedLimit = 6000
    @State private var isLoading = true
    @State private var isSaving = false
    @State private var loadError: String?

    private var cut: Int {
        guard candidates.indices.contains(candidateIndex) else { return 0 }
        return candidates[candidateIndex].offset
    }

    private var leftText: String { String(concat.prefix(cut)) }
    private var rightText: String { String(concat.dropFirst(cut)) }
    private var oversized: Bool {
        leftText.count > oversizedLimit || rightText.count > oversizedLimit
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("调整分段")
                .font(.title2.weight(.semibold))
            Text("拖动中间的分界线，切点会吸附到句子或段落边界。保存后只重新摘要这两段。")
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            if isLoading {
                ProgressView("正在加载原文…")
                    .frame(maxWidth: .infinity, minHeight: 220)
            } else if let loadError {
                Text(loadError)
                    .foregroundStyle(.orange)
                    .frame(maxWidth: .infinity, minHeight: 220, alignment: .leading)
            } else {
                editorBody
            }

            HStack {
                Spacer()
                Button("取消", role: .cancel) { onCancel() }
                    .disabled(isSaving)
                Button {
                    Task { await save() }
                } label: {
                    if isSaving {
                        ProgressView().controlSize(.small)
                    } else {
                        Text("保存并重新摘要")
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(isLoading || isSaving || candidates.isEmpty || loadError != nil)
            }
        }
        .padding(24)
        .frame(width: 640, height: 560)
        .task { await load() }
    }

    @ViewBuilder
    private var editorBody: some View {
        HStack {
            Text("段 \(leftIdx + 1) · \(leftText.count) 字")
            Spacer()
            Text("段 \(leftIdx + 2) · \(rightText.count) 字")
        }
        .font(.callout)
        .foregroundStyle(.secondary)

        VStack(spacing: 0) {
            previewPane(leftText.suffix(480), alignment: .bottom)
            handle
            previewPane(rightText.prefix(480), alignment: .top)
        }
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(LuminaTheme.border, lineWidth: 1)
        )

        HStack {
            Button("上一处") { step(-1) }
                .disabled(candidateIndex <= 0)
            Button("下一处") { step(1) }
                .disabled(candidateIndex >= candidates.count - 1)
            Spacer()
            Text(kindLabel)
                .font(.caption)
                .foregroundStyle(.secondary)
        }

        if oversized {
            Text("其中一段超过 \(oversizedLimit) 字，摘要时可能会截断。仍可保存。")
                .font(.callout)
                .foregroundStyle(.orange)
        }
    }

    private var kindLabel: String {
        guard candidates.indices.contains(candidateIndex) else { return "" }
        switch candidates[candidateIndex].kind {
        case "heading": return "吸附：章节"
        case "paragraph": return "吸附：段落"
        case "current": return "当前分界"
        default: return "吸附：句子"
        }
    }

    private var handle: some View {
        HStack(spacing: 8) {
            Capsule()
                .fill(LuminaTheme.accent)
                .frame(width: 48, height: 4)
            Text("拖动调整")
                .font(.caption.weight(.medium))
                .foregroundStyle(LuminaTheme.accent)
            Capsule()
                .fill(LuminaTheme.accent)
                .frame(width: 48, height: 4)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 10)
        .background(LuminaTheme.accentMuted.opacity(0.5))
        .contentShape(Rectangle())
        .gesture(
            DragGesture(minimumDistance: 2)
                .onChanged { value in
                    let delta = Int((-value.translation.height / 22).rounded())
                    candidateIndex = clampIndex(dragStartIndex + delta)
                }
                .onEnded { _ in
                    dragStartIndex = candidateIndex
                }
        )
        .onAppear { dragStartIndex = candidateIndex }
        .help("上下拖动以改分界")
    }

    private func previewPane(_ text: Substring, alignment: Alignment) -> some View {
        ScrollView {
            Text(String(text))
                .font(.body)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(12)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: alignment)
        .background(LuminaTheme.surface)
    }

    private func step(_ delta: Int) {
        candidateIndex = clampIndex(candidateIndex + delta)
        dragStartIndex = candidateIndex
    }

    private func clampIndex(_ value: Int) -> Int {
        guard !candidates.isEmpty else { return 0 }
        return min(max(0, value), candidates.count - 1)
    }

    private func load() async {
        isLoading = true
        loadError = nil
        do {
            async let leftTask = core.getSegment(bookId: bookId, idx: leftIdx)
            async let rightTask = core.getSegment(bookId: bookId, idx: leftIdx + 1)
            async let previewTask = core.fetchSegmentBoundary(bookId: bookId, idx: leftIdx)
            let left = try await leftTask
            let right = try await rightTask
            let preview = try await previewTask
            concat = (left.raw_text ?? "") + (right.raw_text ?? "")
            candidates = preview.candidates
            oversizedLimit = preview.oversized_limit
            if let match = candidates.firstIndex(where: { $0.offset == preview.left_char_count }) {
                candidateIndex = match
            } else {
                candidateIndex = 0
            }
            dragStartIndex = candidateIndex
        } catch {
            loadError = error.localizedDescription
        }
        isLoading = false
    }

    private func save() async {
        guard !isSaving else { return }
        isSaving = true
        defer { isSaving = false }
        do {
            let result = try await core.moveSegmentBoundary(
                bookId: bookId,
                idx: leftIdx,
                leftCharCount: cut
            )
            onApplied(result, leftText, rightText)
        } catch {
            loadError = error.localizedDescription
        }
    }
}
