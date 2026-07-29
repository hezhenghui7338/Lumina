import SwiftUI

/// Segment summary reading surface: lead sentences on top, structured bullets below.
struct SummaryBlock: View {
    let json: String
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

    private var parsed: ParsedSummary? {
        ParsedSummary(json: json)
    }

    var body: some View {
        if let parsed, parsed.hasContent {
            content(parsed)
        } else if !json.isEmpty {
            parseFailurePlaceholder
        }
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
            headerRow(summary)

            if !summary.sentences.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("总结")
                        .font(.system(size: LuminaTheme.summaryLabelSize, weight: .semibold))
                        .foregroundStyle(LuminaTheme.textSecondary)
                        .tracking(0.6)

                    VStack(alignment: .leading, spacing: LuminaTheme.summaryLeadParagraphSpacing) {
                        ForEach(Array(summary.sentences.enumerated()), id: \.offset) { _, sentence in
                            Text(sentence)
                                .font(.system(size: LuminaTheme.summaryLeadSize, weight: .regular))
                                .foregroundStyle(LuminaTheme.textPrimary)
                                .lineSpacing(LuminaTheme.summaryLeadLineSpacing)
                                .fixedSize(horizontal: false, vertical: true)
                                .textSelection(.enabled)
                        }
                    }
                }
            }

            if !summary.bullets.isEmpty {
                summarySection(title: "结构化要点") {
                    VStack(alignment: .leading, spacing: LuminaTheme.summaryBulletItemSpacing) {
                        ForEach(Array(summary.bullets.enumerated()), id: \.offset) { index, bullet in
                            StructuredBulletRow(index: index + 1, bullet: bullet)
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
                                Text(note)
                                    .font(.system(size: LuminaTheme.summaryBulletSize, weight: .regular))
                                    .foregroundStyle(LuminaTheme.textSecondary)
                                    .lineSpacing(LuminaTheme.summaryBulletLineSpacing)
                                    .fixedSize(horizontal: false, vertical: true)
                                    .textSelection(.enabled)
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
                    Text(label)
                        .font(.system(size: LuminaTheme.summaryBulletSize, weight: .semibold))
                        .foregroundStyle(LuminaTheme.textPrimary)
                        .fixedSize(horizontal: false, vertical: true)
                        .textSelection(.enabled)
                }
                Text(bullet.body)
                    .font(.system(size: LuminaTheme.summaryBulletSize, weight: .regular))
                    .foregroundStyle(
                        bullet.label == nil
                            ? LuminaTheme.textPrimary
                            : LuminaTheme.textSecondary
                    )
                    .lineSpacing(LuminaTheme.summaryBulletLineSpacing)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
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

    init?(json: String) {
        guard let data = json.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return nil }

        sentences = Self.parseStringArray(obj["sentences"])
        bullets = Self.parseBullets(from: obj["bullets"])
        notes = Self.parseStringArray(obj["notes"])
        followUps = Self.parseStringArray(obj["follow_ups"])

        if let a = obj["anchor"] as? String {
            let trimmed = a.trimmingCharacters(in: .whitespacesAndNewlines)
            anchor = trimmed.isEmpty ? nil : trimmed
        } else {
            anchor = nil
        }
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
