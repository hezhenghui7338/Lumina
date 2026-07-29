import Foundation

struct ParsedNewsSummary: Equatable {
    let bodyMarkdown: String
    let followUps: [String]
}

struct ParsedNewsStructuredSummary: Equatable {
    let sentences: [String]
    let bullets: [ParsedBullet]
    let notes: [String]
    let followUps: [String]

    var hasContent: Bool {
        !sentences.isEmpty || !bullets.isEmpty || !notes.isEmpty
    }
}

private enum NewsSummarySectionKind {
    case none
    case summary
    case bullets
    case notes
    case followUps
}

enum NewsSummaryMarkdown {
    private static let askHeadingMarker = "你可以接着问"

    static func parse(_ markdown: String) -> ParsedNewsSummary {
        let structured = parseStructured(markdown)
        var bodyParts: [String] = []
        if !structured.sentences.isEmpty {
            bodyParts.append("## 总结\n" + structured.sentences.joined(separator: "\n"))
        }
        if !structured.bullets.isEmpty {
            let lines = structured.bullets.map { bullet in
                if let label = bullet.label, !label.isEmpty {
                    return "- **\(label)**：\(bullet.body)"
                }
                return "- \(bullet.body)"
            }
            bodyParts.append("## 结构化要点\n" + lines.joined(separator: "\n"))
        }
        if !structured.notes.isEmpty {
            bodyParts.append("## 需要注意\n" + structured.notes.map { "- \($0)" }.joined(separator: "\n"))
        }
        let body = bodyParts.joined(separator: "\n\n").trimmingCharacters(in: .whitespacesAndNewlines)
        return ParsedNewsSummary(
            bodyMarkdown: body.isEmpty ? markdown : body,
            followUps: structured.followUps
        )
    }

    static func parseStructured(_ markdown: String) -> ParsedNewsStructuredSummary {
        var currentSection: NewsSummarySectionKind = .none
        var sentences: [String] = []
        var bullets: [ParsedBullet] = []
        var notes: [String] = []
        var followUps: [String] = []

        for line in markdown.components(separatedBy: "\n") {
            let trimmed = line.trimmingCharacters(in: .whitespaces)

            if trimmed.hasPrefix("##") {
                currentSection = sectionKind(from: trimmed)
                continue
            }

            if trimmed.isEmpty { continue }

            switch currentSection {
            case .summary:
                sentences.append(trimmed)
            case .bullets:
                if let bullet = parseBulletLine(trimmed) {
                    bullets.append(bullet)
                }
            case .notes:
                if let note = parseNoteLine(trimmed) {
                    notes.append(note)
                }
            case .followUps:
                if let question = parseQuestionLine(trimmed) {
                    followUps.append(question)
                }
            case .none:
                break
            }
        }

        return ParsedNewsStructuredSummary(
            sentences: sentences,
            bullets: bullets,
            notes: notes,
            followUps: followUps
        )
    }

    private static func sectionKind(from heading: String) -> NewsSummarySectionKind {
        if heading.contains("总结") { return .summary }
        if heading.contains("结构化要点") { return .bullets }
        if heading.contains("需要注意") { return .notes }
        if heading.contains(askHeadingMarker) { return .followUps }
        return .none
    }

    private static func parseBulletLine(_ line: String) -> ParsedBullet? {
        var text = line
        if text.hasPrefix("- ") {
            text = String(text.dropFirst(2))
        } else if text.hasPrefix("* ") {
            text = String(text.dropFirst(2))
        } else if text.hasPrefix("• ") {
            text = String(text.dropFirst(2))
        } else {
            return nil
        }

        text = text.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty else { return nil }

        if text.hasPrefix("**") {
            let afterOpen = text.index(text.startIndex, offsetBy: 2)
            if let closeRange = text.range(of: "**", range: afterOpen..<text.endIndex) {
                let label = String(text[afterOpen..<closeRange.lowerBound])
                var body = String(text[closeRange.upperBound...]).trimmingCharacters(in: .whitespaces)
                if body.hasPrefix("：") || body.hasPrefix(":") {
                    body = String(body.dropFirst()).trimmingCharacters(in: .whitespaces)
                }
                body = stripCitationSuffix(body)
                return ParsedBullet(label: label, body: body)
            }
        }

        return ParsedBullet(label: nil, body: stripCitationSuffix(text))
    }

    private static func parseNoteLine(_ line: String) -> String? {
        var text = line
        if text.hasPrefix("- ") {
            text = String(text.dropFirst(2))
        } else if text.hasPrefix("* ") {
            text = String(text.dropFirst(2))
        } else if text.hasPrefix("• ") {
            text = String(text.dropFirst(2))
        } else if text.hasPrefix("·") {
            text = String(text.dropFirst(1))
        }
        text = text.trimmingCharacters(in: .whitespaces)
        return text.isEmpty ? nil : text
    }

    private static func stripCitationSuffix(_ text: String) -> String {
        if let range = text.range(of: " — 依据：") {
            return String(text[..<range.lowerBound]).trimmingCharacters(in: .whitespaces)
        }
        if let range = text.range(of: " - 依据：") {
            return String(text[..<range.lowerBound]).trimmingCharacters(in: .whitespaces)
        }
        return text.trimmingCharacters(in: .whitespaces)
    }

    private static func parseQuestionLine(_ line: String) -> String? {
        if let match = line.range(of: #"^\d+\.\s+"#, options: .regularExpression) {
            let question = String(line[match.upperBound...]).trimmingCharacters(in: .whitespaces)
            return question.isEmpty ? nil : question
        }
        if line.hasPrefix("- ") {
            let question = String(line.dropFirst(2)).trimmingCharacters(in: .whitespaces)
            return question.isEmpty ? nil : question
        }
        if line.hasPrefix("* ") {
            let question = String(line.dropFirst(2)).trimmingCharacters(in: .whitespaces)
            return question.isEmpty ? nil : question
        }
        return nil
    }
}
