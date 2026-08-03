import Foundation

enum ChatMetricsFormatter {
    static func attribution(
        provider: String?,
        model: String?,
        tps: Double?,
        totalTokens: Int?,
        promptTokens: Int?,
        completionTokens: Int?,
        durationMs: Int?
    ) -> String? {
        var parts: [String] = ["深聊"]
        if let provider, !provider.isEmpty {
            parts.append(providerLabel(provider))
        }
        if let model, !model.isEmpty {
            parts.append(model)
        }
        if let tps, tps > 0 {
            parts.append(String(format: "%.0f tok/s", tps))
        }
        if let tokenLabel = tokensLabel(
            totalTokens: totalTokens,
            promptTokens: promptTokens,
            completionTokens: completionTokens
        ) {
            parts.append(tokenLabel)
        }
        if let durationMs, durationMs >= 0 {
            parts.append(SummaryMetricsFormatter.duration(seconds: Double(durationMs) / 1000.0))
        }
        // Need at least one metric beyond the "深聊" prefix.
        return parts.count > 1 ? parts.joined(separator: " · ") : nil
    }

    static func attribution(for message: ChatMessage) -> String? {
        attribution(
            provider: message.provider,
            model: message.model,
            tps: message.tps,
            totalTokens: message.total_tokens,
            promptTokens: message.prompt_tokens,
            completionTokens: message.completion_tokens,
            durationMs: message.duration_ms
        )
    }

    static func providerLabel(_ provider: String) -> String {
        switch provider {
        case "ollama": return "Ollama"
        case "openai": return "OpenAI"
        case "openrouter": return "OpenRouter"
        case "aiping": return "Aiping"
        case "cursor": return "Cursor"
        default: return provider
        }
    }

    private static func tokensLabel(
        totalTokens: Int?,
        promptTokens: Int?,
        completionTokens: Int?
    ) -> String? {
        if let totalTokens, totalTokens > 0 {
            return "\(formattedCount(totalTokens)) tokens"
        }
        var parts: [String] = []
        if let promptTokens, promptTokens > 0 {
            parts.append("↑\(formattedCount(promptTokens))")
        }
        if let completionTokens, completionTokens > 0 {
            parts.append("↓\(formattedCount(completionTokens))")
        }
        return parts.isEmpty ? nil : parts.joined(separator: " ") + " tokens"
    }

    private static func formattedCount(_ count: Int) -> String {
        if count >= 1000 {
            let value = Double(count) / 1000.0
            if value >= 10 {
                return String(format: "%.0fk", value)
            }
            return String(format: "%.1fk", value)
        }
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        return formatter.string(from: NSNumber(value: count)) ?? "\(count)"
    }
}
