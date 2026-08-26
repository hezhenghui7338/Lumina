import SwiftUI

/// Tapping the library-wide 进行中/排队 chip opens the bookshelf 「摘要中」 collection.
/// The stop (x) control stays a separate action and must not share this destination.
enum SummarizeActivityNavigationPolicy {
    static let destinationCollection: LibraryCollection = .summarizing
    static let statusTapHelp = "查看摘要中的书籍"
    static let statusTapHint = "打开书架的摘要中目录"
}

/// Compact toolbar capsule for in-flight summaries: status + quiet stop (not a filled stop square).
struct SummarizeActivityChip: View {
    let running: Int
    let queued: Int
    var indexing: Int = 0
    var stalledReason: String? = nil
    var isBusy: Bool = false
    var onStatusTap: (() -> Void)? = nil
    var onStop: () -> Void

    /// Human reason for "queued but nothing running", so the chip never reads as a hang.
    static func stalledLabel(_ reason: String?) -> String? {
        switch reason {
        case "indexing": return "正在建索引"
        case "chat_preempt": return "深聊占用模型"
        case "llm_slots_busy": return "模型并发已满"
        case "no_worker": return "worker 未启动"
        case "starting": return "即将开始"
        default: return nil
        }
    }

    static func statusLabel(
        running: Int,
        queued: Int,
        indexing: Int = 0,
        stalledReason: String? = nil
    ) -> String {
        var parts: [String] = []
        if running > 0 { parts.append("\(running) 进行中") }
        if queued > 0 { parts.append("\(queued) 排队") }
        if indexing > 0 { parts.append("\(indexing) 建索引") }
        if running == 0, queued > 0, let reason = stalledLabel(stalledReason) {
            parts.append(reason)
        }
        if parts.isEmpty { parts.append("\(running) 进行中") }
        return parts.joined(separator: " · ")
    }

    static func shouldShow(activeCount: Int) -> Bool {
        activeCount > 0
    }

    private var statusText: String {
        Self.statusLabel(
            running: running,
            queued: queued,
            indexing: indexing,
            stalledReason: stalledReason
        )
    }

    var body: some View {
        HStack(spacing: 6) {
            statusLabelView

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
        .padding(.trailing, 6)
        .frame(height: 22)
        .background(Capsule().fill(LuminaTheme.accentMuted))
        .overlay(Capsule().stroke(LuminaTheme.border, lineWidth: 0.5))
    }

    @ViewBuilder
    private var statusLabelView: some View {
        let text = Text(statusText)
            .font(.caption)
            .foregroundStyle(LuminaTheme.textSecondary)
            .lineLimit(1)
            .padding(.leading, 10)
            .padding(.vertical, 4)
            .contentShape(Rectangle())

        if let onStatusTap {
            Button(action: onStatusTap) {
                text
            }
            .buttonStyle(.plain)
            .help(SummarizeActivityNavigationPolicy.statusTapHelp)
            .accessibilityLabel(statusText)
            .accessibilityHint(SummarizeActivityNavigationPolicy.statusTapHint)
        } else {
            text
        }
    }
}
