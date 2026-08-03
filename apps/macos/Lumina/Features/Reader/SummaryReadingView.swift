import SwiftUI

/// Segment summary reading surface: lead sentences on top, structured bullets below.
struct SummaryBlock: View {
    let parsedSummary: ParsedSummary?
    var rawJSON: String?
    var provider: String?
    var model: String?
    var charCount: Int?
    var segmentIndex: Int?
    var segmentTotal: Int?
    var fallbackAnchor: String?
    var summaryDurationS: Double?
    var summaryLlmAttempts: Int?
    var onFollowUp: ((String) -> Void)?
    var showsBackground: Bool = true
    var showsHeader: Bool = true

    var body: some View {
        if let summary = resolvedSummary, summary.hasContent {
            content(summary)
        } else if let rawJSON, !rawJSON.isEmpty {
            parseFailurePlaceholder
        }
    }

    /// Prefer pre-parsed cache; fall back to synchronous parse when cache is not wired yet.
    private var resolvedSummary: ParsedSummary? {
        if let parsedSummary, parsedSummary.hasContent { return parsedSummary }
        if let rawJSON, let parsed = ParsedSummary(json: rawJSON), parsed.hasContent {
            return parsed
        }
        return nil
    }

    private var parseFailurePlaceholder: some View {
        Text("摘要格式异常，请重试")
            .font(.system(size: LuminaTheme.summaryBulletSize))
            .foregroundStyle(LuminaTheme.textSecondary)
            .readingColumn()
    }

    @ViewBuilder
    private func content(_ summary: ParsedSummary) -> some View {
        VStack(alignment: .leading, spacing: LuminaTheme.summarySectionSpacing) {
            if showsHeader {
                headerRow(summary)
            }

            if !summary.sentences.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("总结")
                        .font(.system(size: LuminaTheme.summaryLabelSize, weight: .semibold))
                        .foregroundStyle(LuminaTheme.textSecondary)
                        .tracking(0.6)

                    VStack(alignment: .leading, spacing: LuminaTheme.summaryLeadParagraphSpacing) {
                        ForEach(Array(summary.sentences.enumerated()), id: \.offset) { _, sentence in
                            LuminaSelectableText(
                                text: sentence,
                                fontSize: LuminaTheme.summaryLeadSize,
                                lineSpacing: LuminaTheme.summaryLeadLineSpacing
                            )
                        }
                    }
                }
            }

            if !summary.bullets.isEmpty {
                summarySection(title: "结构化要点") {
                    VStack(alignment: .leading, spacing: LuminaTheme.summaryBulletItemSpacing) {
                        ForEach(Array(summary.bullets.enumerated()), id: \.offset) { index, bullet in
                            StructuredBulletRow(
                                index: index + 1,
                                bullet: bullet
                            )
                        }
                    }
                }
            }

            if !summary.notes.isEmpty {
                summarySection(title: "需要注意") {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(Array(summary.notes.enumerated()), id: \.offset) { _, note in
                            HStack(alignment: .top, spacing: 8) {
                                Text("·")
                                    .font(.system(size: LuminaTheme.summaryBulletSize, weight: .semibold))
                                    .foregroundStyle(LuminaTheme.textSecondary)
                                LuminaSelectableText(
                                    text: note,
                                    foreground: LuminaTheme.textSecondary
                                )
                            }
                        }
                    }
                }
            }

            if !summary.followUps.isEmpty {
                summarySection(title: "你可以接着问") {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(Array(summary.followUps.enumerated()), id: \.offset) { index, question in
                            if let onFollowUp {
                                Button {
                                    onFollowUp(question)
                                } label: {
                                    FollowUpChip(text: question, index: index + 1)
                                }
                                .buttonStyle(.plain)
                                .accessibilityIdentifier("lumina.reader.control.followUp.\(index + 1)")
                            } else {
                                FollowUpChip(text: question, index: index + 1)
                            }
                        }
                    }
                }
            }

            if let attribution = summaryAttribution {
                Text(attribution)
                    .font(.caption)
                    .foregroundStyle(LuminaTheme.textSecondary)
                    .padding(.top, 4)
            }
        }
        .modifier(SummaryBlockChrome(showsBackground: showsBackground))
    }

    private struct SummaryBlockChrome: ViewModifier {
        let showsBackground: Bool

        func body(content: Content) -> some View {
            if showsBackground {
                content
                    .padding(LuminaTheme.summaryPadding)
                    .readingColumn()
                    .background(
                        RoundedRectangle(cornerRadius: LuminaTheme.summaryCornerRadius)
                            .fill(LuminaTheme.accentMuted.opacity(0.45))
                    )
            } else {
                content
                    .readingColumn()
            }
        }
    }

    @ViewBuilder
    private func summarySection<Content: View>(title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Divider()
                .background(LuminaTheme.border)

            Text(title)
                .font(.system(size: LuminaTheme.summaryLabelSize, weight: .semibold))
                .foregroundStyle(LuminaTheme.textSecondary)
                .tracking(0.6)

            content()
        }
    }

    @ViewBuilder
    private func headerRow(_ summary: ParsedSummary) -> some View {
        let anchorText: String? = {
            if let anchor = summary.anchor, !anchor.isEmpty {
                return anchor.hasPrefix("〔") ? anchor : "〔\(anchor)〕"
            }
            if let fallback = fallbackAnchor, !fallback.isEmpty {
                return fallback.hasPrefix("〔") ? fallback : "〔\(fallback)〕"
            }
            return nil
        }()

        VStack(alignment: .leading, spacing: 4) {
            if let anchorText {
                Text(anchorText)
                    .font(.system(size: LuminaTheme.summaryLabelSize, weight: .medium))
                    .foregroundStyle(LuminaTheme.textSecondary)
                    .textSelection(.enabled)
            }

            if metaLine != nil {
                Text(metaLine ?? "")
                    .font(.system(size: LuminaTheme.summaryLabelSize - 1))
                    .foregroundStyle(LuminaTheme.textSecondary.opacity(0.85))
                    .textSelection(.enabled)
            }
        }
    }

    private var metaLine: String? {
        var parts: [String] = []
        if let charCount, charCount > 0 {
            parts.append("约 \(Self.formattedCount(charCount)) 字")
        }
        if let segmentIndex, let segmentTotal, segmentTotal > 0 {
            parts.append("段 \(segmentIndex + 1)/\(segmentTotal)")
        }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    private static func formattedCount(_ count: Int) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        return formatter.string(from: NSNumber(value: count)) ?? "\(count)"
    }

    private var summaryAttribution: String? {
        guard let provider, !provider.isEmpty,
              let model, !model.isEmpty else { return nil }
        var parts = ["摘要 · \(Self.providerLabel(provider)) · \(model)"]
        if let metrics = SummaryMetricsFormatter.completedMetricsLabel(
            durationS: summaryDurationS,
            llmAttempts: summaryLlmAttempts
        ) {
            parts.append(metrics)
        }
        return parts.joined(separator: " · ")
    }

    private static func providerLabel(_ provider: String) -> String {
        switch provider {
        case "ollama": return "Ollama"
        case "openai": return "OpenAI"
        case "openrouter": return "OpenRouter"
        default: return provider
        }
    }
}

// MARK: - Bullet row

private struct StructuredBulletRow: View {
    let index: Int
    let bullet: ParsedBullet

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            RoundedRectangle(cornerRadius: 1)
                .fill(LuminaTheme.accent.opacity(0.55))
                .frame(width: 2)
                .padding(.top, 4)
                .padding(.bottom, 2)

            VStack(alignment: .leading, spacing: 3) {
                if let label = bullet.label, !label.isEmpty {
                    LuminaSelectableText(
                        text: label,
                        fontWeight: .semibold
                    )
                }
                LuminaSelectableText(
                    text: bullet.body,
                    foreground: bullet.label == nil
                        ? LuminaTheme.textPrimary
                        : LuminaTheme.textSecondary
                )
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(accessibilityText)
    }

    private var accessibilityText: String {
        if let label = bullet.label {
            return "\(index). \(label)：\(bullet.body)"
        }
        return "\(index). \(bullet.body)"
    }
}

// MARK: - Parsing

struct ParsedBullet: Equatable {
    var label: String?
    var body: String
}

struct ParsedSummary: Equatable {
    var sentences: [String]
    var bullets: [ParsedBullet]
    var notes: [String]
    var followUps: [String]
    var anchor: String?

    var hasContent: Bool {
        !sentences.isEmpty || !bullets.isEmpty || !notes.isEmpty || !followUps.isEmpty
    }

    /// Plain text for clipboard copy of the full summary panel.
    var copyablePlainText: String {
        var sections: [String] = []

        if !sentences.isEmpty {
            var block = "总结"
            for sentence in sentences {
                block += "\n\(sentence)"
            }
            sections.append(block)
        }

        if !bullets.isEmpty {
            var block = "结构化要点"
            for (index, bullet) in bullets.enumerated() {
                if let label = bullet.label, !label.isEmpty {
                    block += "\n\(index + 1). \(label)：\(bullet.body)"
                } else {
                    block += "\n\(index + 1). \(bullet.body)"
                }
            }
            sections.append(block)
        }

        if !notes.isEmpty {
            var block = "需要注意"
            for note in notes {
                block += "\n· \(note)"
            }
            sections.append(block)
        }

        if !followUps.isEmpty {
            var block = "你可以接着问"
            for (index, question) in followUps.enumerated() {
                block += "\n\(index + 1). \(question)"
            }
            sections.append(block)
        }

        return sections.joined(separator: "\n\n")
    }

    init?(json: String) {
        guard let obj = Self.extractJSONObject(from: json) else { return nil }

        sentences = Self.parseStringArray(obj["sentences"])
        bullets = Self.parseBullets(from: obj["bullets"])
        notes = Self.parseStringArray(obj["notes"])
        followUps = Self.parseStringArray(obj["follow_ups"])

        let anchorRaw = (obj["anchor"] as? String) ?? (obj["锚点"] as? String)
        if let a = anchorRaw {
            let trimmed = a.trimmingCharacters(in: .whitespacesAndNewlines)
            anchor = trimmed.isEmpty ? nil : trimmed
        } else {
            anchor = nil
        }
    }

    /// Lenient JSON extraction — strips markdown fences and prose wrappers (legacy LLM output).
    private static func extractJSONObject(from raw: String) -> [String: Any]? {
        let candidates = jsonCandidates(from: raw)
        for candidate in candidates {
            guard let data = candidate.data(using: .utf8),
                  let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            else { continue }
            return obj
        }
        return nil
    }

    private static func jsonCandidates(from raw: String) -> [String] {
        var text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.hasPrefix("```") {
            if let firstNewline = text.firstIndex(of: "\n") {
                text = String(text[text.index(after: firstNewline)...])
            }
            if text.hasSuffix("```") {
                text = String(text.dropLast(3)).trimmingCharacters(in: .whitespacesAndNewlines)
            }
        }

        var candidates = [text]
        if let start = text.firstIndex(of: "{"), let end = text.lastIndex(of: "}" ), start < end {
            candidates.append(String(text[start...end]))
        }
        return candidates
    }

    /// First bullet line for segment sidebar preview (no JSON re-parse in views).
    var bulletPreviewLine: String? {
        guard let first = bullets.first else { return nil }
        if let label = first.label, !label.isEmpty {
            return "\(label)：\(first.body)"
        }
        return first.body
    }

    /// Parse many summaries off the main thread.
    static func parseBatch(_ items: [(idx: Int, json: String)]) -> [Int: ParsedSummary] {
        var result: [Int: ParsedSummary] = [:]
        result.reserveCapacity(items.count)
        for (idx, json) in items {
            if let parsed = ParsedSummary(json: json) {
                result[idx] = parsed
            }
        }
        return result
    }

    private static func parseStringArray(_ value: Any?) -> [String] {
        (value as? [String] ?? [])
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    private static func parseBullets(from value: Any?) -> [ParsedBullet] {
        guard let items = value as? [Any] else { return [] }
        return items.compactMap { item in
            if let dict = item as? [String: Any] {
                return parseBulletObject(dict)
            }
            if let text = item as? String {
                let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !trimmed.isEmpty else { return nil }
                return parseBullet(trimmed)
            }
            return nil
        }
    }

    private static func parseBulletObject(_ dict: [String: Any]) -> ParsedBullet? {
        let label = (dict["label"] as? String)?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let body = (dict["body"] as? String ?? dict["content"] as? String ?? dict["text"] as? String)?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if let body, !body.isEmpty {
            if let label, !label.isEmpty {
                return ParsedBullet(label: label, body: body)
            }
            return ParsedBullet(label: nil, body: body)
        }
        if let label, !label.isEmpty {
            return ParsedBullet(label: label, body: label)
        }
        return nil
    }

    /// Parse `**标签**：内容` / `标签：内容` / plain body.
    static func parseBullet(_ raw: String) -> ParsedBullet {
        var text = raw
        while text.hasPrefix("- ") || text.hasPrefix("• ") || text.hasPrefix("* ") {
            text = String(text.dropFirst(2)).trimmingCharacters(in: .whitespaces)
        }

        if text.hasPrefix("**"),
           let close = text.range(of: "**", range: text.index(text.startIndex, offsetBy: 2)..<text.endIndex) {
            let label = String(text[text.index(text.startIndex, offsetBy: 2)..<close.lowerBound])
                .trimmingCharacters(in: .whitespacesAndNewlines)
            var rest = String(text[close.upperBound...]).trimmingCharacters(in: .whitespacesAndNewlines)
            if rest.hasPrefix("：") || rest.hasPrefix(":") {
                rest = String(rest.dropFirst()).trimmingCharacters(in: .whitespacesAndNewlines)
            }
            if !label.isEmpty, !rest.isEmpty {
                return ParsedBullet(label: label, body: rest)
            }
        }

        for sep in ["：", ":"] {
            if let range = text.range(of: sep) {
                let label = String(text[..<range.lowerBound]).trimmingCharacters(in: .whitespacesAndNewlines)
                let body = String(text[range.upperBound...]).trimmingCharacters(in: .whitespacesAndNewlines)
                if !label.isEmpty, !body.isEmpty, label.count <= 12, !label.contains("。") {
                    return ParsedBullet(label: label, body: body)
                }
            }
        }

        return ParsedBullet(label: nil, body: text)
    }
}
