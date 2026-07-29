import SwiftUI

struct TaskRowView: View {
    let task: OpsTask
    var onCancel: (() -> Void)?

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: kindIcon)
                .foregroundStyle(statusColor)
                .frame(width: 20)
            VStack(alignment: .leading, spacing: 2) {
                Text(task.subject_label)
                    .font(.body)
                    .lineLimit(1)
                Text(task.detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                HStack(spacing: 8) {
                    if task.status == "running" {
                        TimelineView(.periodic(from: .now, by: 1)) { context in
                            Text(runningStatusLabel(at: context.date))
                                .font(.caption2)
                                .foregroundStyle(statusColor)
                        }
                    } else if task.status == "queued" {
                        Text("排队")
                            .font(.caption2)
                            .foregroundStyle(statusColor)
                    } else if task.status == "paused" {
                        Text("已暂停")
                            .font(.caption2)
                            .foregroundStyle(statusColor)
                    } else {
                        Text(completedStatusLabel)
                            .font(.caption2)
                            .foregroundStyle(statusColor)
                    }
                    if let resource = task.resource_id, !resource.isEmpty {
                        Text(resource)
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                    }
                }
                if let error = task.error, !error.isEmpty {
                    Text(error)
                        .font(.caption2)
                        .foregroundStyle(.red)
                        .lineLimit(2)
                }
            }
            Spacer(minLength: 0)
            if task.cancellable, task.status == "running" || task.status == "queued", let onCancel {
                Button("取消", role: .destructive, action: onCancel)
                    .buttonStyle(.borderless)
                    .font(.caption)
            }
        }
        .padding(.vertical, 2)
    }

    private func runningStatusLabel(at now: Date) -> String {
        var parts = [statusLabel]
        if let duration = task.duration_s {
            parts.append(SummaryMetricsFormatter.duration(seconds: duration))
        } else if let startedAt = SummaryMetricsFormatter.parseISO8601(task.started_at) {
            let elapsed = max(0, now.timeIntervalSince(startedAt))
            parts.append(SummaryMetricsFormatter.duration(seconds: elapsed))
        }
        if let attempt = task.llm_attempt {
            parts.append(
                SummaryMetricsFormatter.attemptLabel(
                    attempt: attempt,
                    maxAttempts: task.max_llm_attempts
                )
            )
        }
        return parts.joined(separator: " · ")
    }

    private var completedStatusLabel: String {
        var parts = [statusLabel]
        if let duration = task.duration_s {
            parts.append(SummaryMetricsFormatter.duration(seconds: duration))
        }
        if let attempt = task.llm_attempt, attempt > 0 {
            parts.append("\(attempt) 次尝试")
        }
        return parts.joined(separator: " · ")
    }

    private var kindIcon: String {
        switch task.kind {
        case "summarize": return "text.alignleft"
        case "translate": return "character.bubble"
        case "classify": return "tag"
        case "book_chat", "news_chat": return "bubble.left.and.bubble.right"
        case "news_read": return "newspaper"
        default: return "cpu"
        }
    }

    private var statusLabel: String {
        switch task.status {
        case "queued": return "排队"
        case "running": return "运行中"
        case "paused": return "已暂停"
        case "completed": return "已完成"
        case "failed": return "失败"
        case "cancelled": return "已取消"
        default: return task.status
        }
    }

    private var statusColor: Color {
        switch task.status {
        case "running": return .accentColor
        case "queued": return .secondary
        case "paused": return .orange
        case "failed": return .red
        case "cancelled": return .orange
        default: return .primary
        }
    }
}
