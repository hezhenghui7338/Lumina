import Foundation

struct SegmentRunningMetrics: Equatable {
    var startedAt: Date
    var llmAttempt: Int
    var maxLlmAttempts: Int?
}

enum SummaryMetricsFormatter {
    static func duration(seconds: Double) -> String {
        let total = max(0, Int(seconds.rounded()))
        if total < 60 {
            return "\(total)s"
        }
        let minutes = total / 60
        let remainder = total % 60
        return remainder == 0 ? "\(minutes)m" : "\(minutes)m \(remainder)s"
    }

    static func attemptLabel(attempt: Int, maxAttempts: Int?) -> String {
        if let maxAttempts, maxAttempts > 0 {
            return "第 \(attempt)/\(maxAttempts) 次尝试"
        }
        return "第 \(attempt) 次尝试"
    }

    static func inProgressLabel(
        startedAt: Date,
        llmAttempt: Int,
        maxLlmAttempts: Int?,
        now: Date = Date()
    ) -> String {
        let elapsed = max(0, now.timeIntervalSince(startedAt))
        var parts = ["摘要生成中", duration(seconds: elapsed)]
        parts.append(attemptLabel(attempt: llmAttempt, maxAttempts: maxLlmAttempts))
        return parts.joined(separator: " · ")
    }

    static func completedMetricsLabel(durationS: Double?, llmAttempts: Int?) -> String? {
        var parts: [String] = []
        if let durationS {
            parts.append(duration(seconds: durationS))
        }
        if let llmAttempts, llmAttempts > 0 {
            parts.append("\(llmAttempts) 次尝试")
        }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    static func failureLabel(durationS: Double?, retryCount: Int?) -> String {
        var parts = ["摘要失败"]
        if let durationS {
            parts.append("耗时 \(duration(seconds: durationS))")
        }
        if let retryCount, retryCount > 0 {
            parts.append("已重试 \(retryCount) 次")
        }
        return parts.joined(separator: " · ")
    }

    static func bookActiveLabel(active: SummarizeActive, now: Date = Date()) -> String? {
        guard let startedAt = active.startedAtDate else { return nil }
        let elapsed = max(0, now.timeIntervalSince(startedAt))
        var parts = ["段 \(active.segment_idx + 1)", duration(seconds: elapsed)]
        parts.append(attemptLabel(attempt: active.llm_attempt, maxAttempts: active.max_llm_attempts))
        return parts.joined(separator: " · ")
    }

    static func parseISO8601(_ value: String) -> Date? {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: value) {
            return date
        }
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: value)
    }
}

struct SummarizeActive: Codable, Hashable {
    let segment_idx: Int
    let started_at: String
    let llm_attempt: Int
    let max_llm_attempts: Int?

    var startedAtDate: Date? {
        SummaryMetricsFormatter.parseISO8601(started_at)
    }
}
