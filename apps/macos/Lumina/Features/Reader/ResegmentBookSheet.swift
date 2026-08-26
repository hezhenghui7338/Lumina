import AppKit
import SwiftUI

enum ResegmentTarget {
    static let minChars = 200
    static let maxChars = 8000
    static let range = minChars...maxChars
    static let presets = [500, 1000, 1500, 2000, 2500]

    static func clamp(_ value: Int, range: ClosedRange<Int> = Self.range) -> Int {
        min(range.upperBound, max(range.lowerBound, value))
    }

    static func normalized(
        currentTarget: Int?,
        totalChars: Int?,
        segmentCount: Int
    ) -> Int {
        let currentAverage = (totalChars ?? 4000) / max(segmentCount, 1)
        let target = currentTarget ?? currentAverage
        return clamp(target)
    }
}

struct ChunkTargetInput: View {
    @Binding var value: Int
    var range: ClosedRange<Int>
    var label: String = "目标大小"

    @State private var draft: String = ""
    @FocusState private var focused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(label)
            HStack(spacing: 8) {
                TextField("", text: $draft)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 88)
                    .focused($focused)
                    .onSubmit { commit() }
                Text("字")
                    .foregroundStyle(.secondary)
            }
            HStack(spacing: 6) {
                ForEach(ResegmentTarget.presets, id: \.self) { preset in
                    presetButton(preset)
                }
            }
        }
        .onAppear { draft = String(value) }
        .onChange(of: value) { _, newValue in
            if !focused {
                draft = String(newValue)
            }
        }
        .onChange(of: focused) { _, isFocused in
            if !isFocused { commit() }
        }
        .onChange(of: draft) { _, text in
            let digits = text.filter(\.isNumber)
            if digits != text {
                draft = digits
                return
            }
            if let parsed = Int(digits), range.contains(parsed) {
                value = parsed
            }
        }
        .onDisappear { commit() }
    }

    @ViewBuilder
    private func presetButton(_ preset: Int) -> some View {
        if value == preset {
            Button("\(preset)") { apply(preset) }
                .buttonStyle(.borderedProminent)
                .controlSize(.small)
        } else {
            Button("\(preset)") { apply(preset) }
                .buttonStyle(.bordered)
                .controlSize(.small)
        }
    }

    private func apply(_ preset: Int) {
        let clamped = ResegmentTarget.clamp(preset, range: range)
        value = clamped
        draft = String(clamped)
        focused = false
    }

    private func commit() {
        if let parsed = Int(draft.trimmingCharacters(in: .whitespacesAndNewlines)) {
            value = ResegmentTarget.clamp(parsed, range: range)
        }
        draft = String(value)
    }
}

struct ResegmentBookSheet: View {
    var bookTitle: String = ""
    @Binding var targetChars: Int
    @Binding var segmentTier: SegmentTier
    @Binding var isPresented: Bool
    var isSubmitting: Bool
    var onSubmit: () -> Void
    @State private var showAdvancedConfirm = false

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("整书重新分段")
                .font(.title2.weight(.semibold))
            if !bookTitle.isEmpty {
                Text("《\(bookTitle)》")
                    .foregroundStyle(.secondary)
            }
            Text("设置每段的目标字数。实际段落会根据章节和语义边界略有调整。")
                .foregroundStyle(.secondary)
            ChunkTargetInput(
                value: $targetChars,
                range: ResegmentTarget.range,
                label: "目标大小"
            )
            Picker("分段档位", selection: $segmentTier) {
                ForEach(SegmentTier.allCases) { tier in
                    Text(tier.label).tag(tier)
                }
            }
            .pickerStyle(.segmented)
            if segmentTier == .advanced {
                Text("高级分段会额外调用模型校准超长或无标点块，更慢、更费配额。")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            Text("重新分段会删除已有摘要、笔记和本书对话记录，且无法撤销。原始书籍文件不会被修改。")
                .font(.callout)
                .foregroundStyle(.orange)
            HStack {
                Spacer()
                Button("取消", role: .cancel) {
                    isPresented = false
                }
                .disabled(isSubmitting)
                Button(action: requestSubmit) {
                    if isSubmitting {
                        ProgressView()
                            .controlSize(.small)
                    } else {
                        Text("开始重新分段")
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(isSubmitting)
            }
        }
        .padding(24)
        .frame(width: 440)
        .confirmationDialog(
            "使用高级分段？",
            isPresented: $showAdvancedConfirm,
            titleVisibility: .visible
        ) {
            Button("确认高级分段", role: .destructive, action: onSubmit)
            Button("取消", role: .cancel) {}
        } message: {
            Text("高级分段会额外调用模型寻找切点，并删除已有摘要、笔记和本书对话记录。")
        }
    }

    private func requestSubmit() {
        NSApp.keyWindow?.makeFirstResponder(nil)
        targetChars = ResegmentTarget.clamp(targetChars)
        if segmentTier == .advanced {
            showAdvancedConfirm = true
        } else {
            onSubmit()
        }
    }
}
