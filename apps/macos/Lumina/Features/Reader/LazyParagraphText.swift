import SwiftUI

struct SourceTextSkeleton: View {
    var lineCount: Int = 4

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(0..<lineCount, id: \.self) { index in
                RoundedRectangle(cornerRadius: 4)
                    .fill(LuminaTheme.border.opacity(0.45))
                    .frame(height: 14)
                    .frame(maxWidth: index == lineCount - 1 ? 180 : .infinity)
            }
        }
        .accessibilityLabel("原文加载中")
    }
}
