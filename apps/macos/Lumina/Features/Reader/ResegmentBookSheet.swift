import SwiftUI

enum ResegmentTarget {
    static let minChars = 200
    static let maxChars = 8000
    static let range = minChars...maxChars

    static func normalized(
        currentTarget: Int?,
        totalChars: Int?,
        segmentCount: Int
    ) -> Int {
        let currentAverage = (totalChars ?? 4000) / max(segmentCount, 1)
        let target = currentTarget ?? currentAverage
        let rounded = ((target + 50) / 100) * 100
        return min(maxChars, max(minChars, rounded))
    }
}

struct ResegmentBookSheet: View {
    var bookTitle: String = ""
    @Binding var targetChars: Int
    @Binding var isPresented: Bool
    var isSubmitting: Bool
    var onSubmit: () -> Void

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
            Stepper(value: $targetChars, in: ResegmentTarget.range, step: 100) {
                Text("目标大小：\(targetChars) 字")
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
                Button(action: onSubmit) {
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
    }
}
