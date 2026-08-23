import SwiftUI

/// Compact toolbar capsule for in-flight summaries: status + quiet stop (not a filled stop square).
struct SummarizeActivityChip: View {
    let running: Int
    let queued: Int
    var isBusy: Bool = false
    var onStop: () -> Void

    static func statusLabel(running: Int, queued: Int) -> String {
        if queued > 0 {
            return "\(running) 进行中 · \(queued) 排队"
        }
        return "\(running) 进行中"
    }

    static func shouldShow(activeCount: Int) -> Bool {
        activeCount > 0
    }

    var body: some View {
        HStack(spacing: 6) {
            Text(Self.statusLabel(running: running, queued: queued))
                .font(.caption)
                .foregroundStyle(LuminaTheme.textSecondary)
                .lineLimit(1)

            if isBusy {
                ProgressView()
                    .controlSize(.mini)
                    .frame(width: 16, height: 16)
            } else {
                Button(action: onStop) {
                    Image(systemName: "xmark")
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(LuminaTheme.textSecondary)
                        .frame(width: 16, height: 16)
                        .background(Circle().fill(Color.primary.opacity(0.08)))
                }
                .buttonStyle(.plain)
                .help("停止全部摘要")
                .accessibilityLabel("停止全部摘要")
            }
        }
        .padding(.leading, 10)
        .padding(.trailing, 6)
        .frame(height: 22)
        .background(Capsule().fill(LuminaTheme.accentMuted))
        .overlay(Capsule().stroke(LuminaTheme.border, lineWidth: 0.5))
    }
}
