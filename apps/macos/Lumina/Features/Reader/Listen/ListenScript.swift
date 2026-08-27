import Foundation

/// Speaker click follows the panel on screen, not only the 摘要|原文 picker.
/// Per-segment 「切换原文 / 切换摘要」 can diverge from the picker; listen must match.
enum ListenChromePolicy {
    static func isShowingOriginal(
        contentMode: ReaderContentMode,
        sourceExpanded: Bool,
        summaryExpanded: Bool
    ) -> Bool {
        switch contentMode {
        case .summary: sourceExpanded
        case .original: !summaryExpanded
        }
    }

    static func primaryMode(showingOriginal: Bool) -> ListenMode {
        showingOriginal ? .original : .summary
    }

    static func showsSummaryChevron(showingOriginal: Bool) -> Bool {
        !showingOriginal
    }
}

enum ListenMode: String, CaseIterable, Equatable {
    case summary
    case detailed
    case original

    var label: String {
        switch self {
        case .summary: "听简要摘要"
        case .detailed: "听完整摘要"
        case .original: "听原文"
        }
    }

    var shortLabel: String {
        switch self {
        case .summary: "简要摘要"
        case .detailed: "完整摘要"
        case .original: "原文"
        }
    }

    var isSummaryLayer: Bool {
        self == .summary || self == .detailed
    }
}

struct ListenUtterance: Equatable {
    var text: String
}

struct ListenScript: Equatable {
    var mode: ListenMode
    var language: String
    var utterances: [ListenUtterance]
    var ready: Bool
    var skipReason: String?

    static let sectionBullets = "结构化要点"
    static let sectionNotes = "需要注意"
    static let maxUtteranceChars = 800

    var texts: [String] { utterances.map(\.text) }

    static func notReady(_ mode: ListenMode, reason: String, language: String = "zh") -> ListenScript {
        ListenScript(mode: mode, language: language, utterances: [], ready: false, skipReason: reason)
    }

    static func detectLanguage(_ text: String) -> String {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return "zh" }
        var cjk = 0
        var letters = 0
        for scalar in trimmed.unicodeScalars {
            if (0x4E00...0x9FFF).contains(scalar.value) {
                cjk += 1
            } else if (0x41...0x5A).contains(scalar.value) || (0x61...0x7A).contains(scalar.value) {
                letters += 1
            }
        }
        return cjk >= max(1, letters) ? "zh" : "en"
    }

    static func build(
        mode: ListenMode,
        summary: ParsedSummary?,
        rawText: String?,
        languageHint: String? = nil
    ) -> ListenScript {
        switch mode {
        case .original:
            let text = (rawText ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            guard !text.isEmpty else {
                return notReady(.original, reason: "empty_text", language: languageHint ?? "zh")
            }
            let utterances = utterances(from: splitSentences(text))
            let language = languageHint ?? detectLanguage(text)
            if utterances.isEmpty {
                return notReady(.original, reason: "empty_text", language: language)
            }
            return ListenScript(mode: .original, language: language, utterances: utterances, ready: true, skipReason: nil)
        case .summary, .detailed:
            guard let summary, summary.hasContent else {
                return notReady(mode, reason: "summary_not_ready", language: languageHint ?? "zh")
            }
            var lines: [String] = summary.sentences.filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
            if mode == .detailed {
                let bullets = summary.bullets.filter { !$0.body.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
                if !bullets.isEmpty {
                    lines.append(sectionBullets)
                    for (index, bullet) in bullets.enumerated() {
                        lines.append(formatBullet(index: index + 1, label: bullet.label, body: bullet.body))
                    }
                }
            }
            let sample = (summary.sentences + summary.bullets.map(\.body) + summary.notes).joined(separator: " ")
            let language = languageHint ?? detectLanguage(sample)
            let utterances = utterances(from: lines)
            if utterances.isEmpty {
                return notReady(mode, reason: "summary_not_ready", language: language)
            }
            return ListenScript(mode: mode, language: language, utterances: utterances, ready: true, skipReason: nil)
        }
    }

    static func formatBullet(index: Int, label: String?, body: String) -> String {
        if let label, !label.isEmpty {
            return "\(index). \(label)。\(body)"
        }
        return "\(index). \(body)"
    }

    static func splitSentences(_ text: String) -> [String] {
        let raw = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !raw.isEmpty else { return [] }
        var result: [String] = []
        var current = ""
        let chars = Array(raw)
        var i = 0
        let cnStops = Set("。！？；")
        while i < chars.count {
            let ch = chars[i]
            if ch == "\n" {
                let piece = current.trimmingCharacters(in: .whitespacesAndNewlines)
                if !piece.isEmpty { result.append(piece) }
                current = ""
                i += 1
                continue
            }
            current.append(ch)
            let isCN = cnStops.contains(ch)
            let isBang = ch == "!" || ch == "?"
            let isPeriod = ch == "." && (i + 1 >= chars.count || !chars[i + 1].isNumber)
            if isCN || isBang || isPeriod {
                var j = i + 1
                while j < chars.count && chars[j].isWhitespace { j += 1 }
                let piece = current.trimmingCharacters(in: .whitespacesAndNewlines)
                if !piece.isEmpty { result.append(piece) }
                current = ""
                i = j
                continue
            }
            i += 1
        }
        let tail = current.trimmingCharacters(in: .whitespacesAndNewlines)
        if !tail.isEmpty { result.append(tail) }
        return result.isEmpty ? [raw] : result
    }

    private static func utterances(from lines: [String]) -> [ListenUtterance] {
        var out: [ListenUtterance] = []
        for line in lines {
            for chunk in chunkLong(line) {
                out.append(ListenUtterance(text: chunk))
            }
        }
        return out
    }

    static func chunkLong(_ text: String, maxChars: Int = maxUtteranceChars) -> [String] {
        let cleaned = text.trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression)
        guard !cleaned.isEmpty else { return [] }
        if cleaned.count <= maxChars { return [cleaned] }
        var chunks: [String] = []
        var remaining = cleaned
        while !remaining.isEmpty {
            if remaining.count <= maxChars {
                chunks.append(remaining)
                break
            }
            let end = remaining.index(remaining.startIndex, offsetBy: maxChars)
            let window = String(remaining[..<end])
            let cut = lastBreak(in: window) ?? maxChars
            let cutIndex = remaining.index(remaining.startIndex, offsetBy: min(cut, remaining.count))
            let piece = remaining[..<cutIndex].trimmingCharacters(in: .whitespacesAndNewlines)
            if !piece.isEmpty { chunks.append(String(piece)) }
            remaining = remaining[cutIndex...].trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return chunks
    }

    private static func lastBreak(in window: String) -> Int? {
        let marks = ["。", "！", "？", "；", "，", ". ", " "]
        var best: Int?
        for mark in marks {
            if let range = window.range(fromEnd: mark) {
                let idx = window.distance(from: window.startIndex, to: range.upperBound)
                if idx >= window.count / 3 {
                    best = max(best ?? 0, idx)
                }
            }
        }
        return best
    }
}

private extension String {
    func range(fromEnd search: String) -> Range<String.Index>? {
        range(of: search, options: .backwards)
    }
}
