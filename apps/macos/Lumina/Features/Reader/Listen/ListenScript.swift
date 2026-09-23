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

/// Where the UI should paint the light follow-along highlight for one TTS utterance.
enum ListenHighlightAnchor: Equatable {
    case segmentTitle
    case summarySentence(Int)
    case sectionBullets
    case bullet(Int)
    /// UTF-16 range into the segment `raw_text` shown in the reader.
    case originalUTF16(location: Int, length: Int)

    var originalNSRange: NSRange? {
        guard case let .originalUTF16(location, length) = self, length > 0 else { return nil }
        return NSRange(location: location, length: length)
    }
}

/// Whether / how to announce chapter before segment label (PRD §5.3.1).
enum ListenChapterSpeakContext: Equatable {
    /// First segment of this listen session (or fresh start).
    case sessionStart
    /// After at least one segment was spoken; compare to last spoken chapter.
    case continuing(previousSpokenChapter: String?)
}

enum ListenChapterAnnouncePolicy {
    static func normalizedChapter(_ raw: String?) -> String? {
        let cleaned = SegmentOutlinePolicy.stripSectionMark(raw ?? "")
        return cleaned.isEmpty ? nil : cleaned
    }

    static func shouldAnnounce(chapter: String?, context: ListenChapterSpeakContext) -> Bool {
        guard let current = normalizedChapter(chapter) else { return false }
        switch context {
        case .sessionStart:
            return true
        case .continuing(let previous):
            return normalizedChapter(previous) != current
        }
    }

    /// Ordered title lines before body: optional chapter, then label (skip duplicate).
    static func titlePrefix(
        segmentLabel: String?,
        chapter: String?,
        context: ListenChapterSpeakContext
    ) -> [String] {
        var lines: [String] = []
        let chapterName = normalizedChapter(chapter)
        let announce = shouldAnnounce(chapter: chapter, context: context)
        if announce, let chapterName {
            lines.append(chapterName)
        }
        if let title = ListenScript.segmentTitle(segmentLabel) {
            if title != chapterName {
                lines.append(title)
            } else if !announce {
                lines.append(title)
            }
        }
        return lines
    }
}

struct ListenUtterance: Equatable {
    var text: String
    var anchor: ListenHighlightAnchor
}

struct ListenScript: Equatable {
    var mode: ListenMode
    var language: String
    var utterances: [ListenUtterance]
    var ready: Bool
    var skipReason: String?

    static let sectionBullets = "主要内容"
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
        languageHint: String? = nil,
        segmentLabel: String? = nil,
        chapter: String? = nil,
        chapterContext: ListenChapterSpeakContext = .sessionStart
    ) -> ListenScript {
        let prefix = ListenChapterAnnouncePolicy.titlePrefix(
            segmentLabel: segmentLabel,
            chapter: chapter,
            context: chapterContext
        )
        switch mode {
        case .original:
            let source = rawText ?? ""
            let trimmed = source.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else {
                return notReady(.original, reason: "empty_text", language: languageHint ?? "zh")
            }
            var utterances: [ListenUtterance] = []
            for line in prefix {
                utterances.append(contentsOf: anchoredChunks(line, anchor: .segmentTitle))
            }
            utterances.append(contentsOf: originalUtterances(in: source))
            let language = languageHint ?? detectLanguage(trimmed)
            if utterances.isEmpty {
                return notReady(.original, reason: "empty_text", language: language)
            }
            return ListenScript(mode: .original, language: language, utterances: utterances, ready: true, skipReason: nil)
        case .summary, .detailed:
            guard let summary, summary.hasContent else {
                return notReady(mode, reason: "summary_not_ready", language: languageHint ?? "zh")
            }
            var utterances: [ListenUtterance] = []
            for line in prefix {
                utterances.append(contentsOf: anchoredChunks(line, anchor: .segmentTitle))
            }
            for (index, sentence) in summary.sentences.enumerated() {
                let cleaned = sentence.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !cleaned.isEmpty else { continue }
                utterances.append(contentsOf: anchoredChunks(cleaned, anchor: .summarySentence(index)))
            }
            if mode == .detailed {
                let bullets = summary.bullets.enumerated().compactMap { index, bullet -> (Int, ParsedBullet)? in
                    let body = bullet.body.trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !body.isEmpty else { return nil }
                    return (index, bullet)
                }
                if !bullets.isEmpty {
                    utterances.append(contentsOf: anchoredChunks(sectionBullets, anchor: .sectionBullets))
                    for (displayIndex, (sourceIndex, bullet)) in bullets.enumerated() {
                        let line = formatBullet(index: displayIndex + 1, label: bullet.label, body: bullet.body)
                        utterances.append(contentsOf: anchoredChunks(line, anchor: .bullet(sourceIndex)))
                    }
                }
            }
            let sample = (prefix + summary.sentences + summary.bullets.map(\.body) + summary.notes)
                .joined(separator: " ")
            let language = languageHint ?? detectLanguage(sample)
            if utterances.isEmpty {
                return notReady(mode, reason: "summary_not_ready", language: language)
            }
            return ListenScript(mode: mode, language: language, utterances: utterances, ready: true, skipReason: nil)
        }
    }

    /// Condensed segment title only; blank means skip (no 段 N fallback).
    static func segmentTitle(_ segmentLabel: String?) -> String? {
        let cleaned = segmentLabel?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return cleaned.isEmpty ? nil : cleaned
    }

    static func formatBullet(index: Int, label: String?, body: String) -> String {
        if let label, !label.isEmpty {
            return "\(index). \(label)。\(body)"
        }
        return "\(index). \(body)"
    }

    static func splitSentences(_ text: String) -> [String] {
        splitSentencePieces(text).map(\.text)
    }

    private static func originalUtterances(in source: String) -> [ListenUtterance] {
        var out: [ListenUtterance] = []
        var searchFrom = source.startIndex
        for piece in splitSentencePieces(source) {
            guard let located = locateUTF16Range(of: piece.text, in: source, from: &searchFrom) else {
                // Speak without a paint range if the substring cannot be relocated.
                out.append(contentsOf: anchoredChunks(
                    piece.text,
                    anchor: .originalUTF16(location: 0, length: 0)
                ))
                continue
            }
            let chunks = chunkLong(piece.text)
            if chunks.count <= 1 {
                out.append(ListenUtterance(text: chunks.first ?? piece.text, anchor: .originalUTF16(
                    location: located.location,
                    length: located.length
                )))
                continue
            }
            // Long sentences: keep the whole sentence range highlighted across chunks.
            for chunk in chunks {
                out.append(ListenUtterance(
                    text: chunk,
                    anchor: .originalUTF16(location: located.location, length: located.length)
                ))
            }
        }
        return out
    }

    private static func anchoredChunks(_ text: String, anchor: ListenHighlightAnchor) -> [ListenUtterance] {
        chunkLong(text).map { ListenUtterance(text: $0, anchor: anchor) }
    }

    private struct SentencePiece {
        var text: String
    }

    private static func splitSentencePieces(_ text: String) -> [SentencePiece] {
        let raw = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !raw.isEmpty else { return [] }
        var result: [SentencePiece] = []
        var current = ""
        let chars = Array(raw)
        var i = 0
        let cnStops = Set("。！？；")
        while i < chars.count {
            let ch = chars[i]
            if ch == "\n" {
                let piece = current.trimmingCharacters(in: .whitespacesAndNewlines)
                if !piece.isEmpty { result.append(SentencePiece(text: piece)) }
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
                if !piece.isEmpty { result.append(SentencePiece(text: piece)) }
                current = ""
                i = j
                continue
            }
            i += 1
        }
        let tail = current.trimmingCharacters(in: .whitespacesAndNewlines)
        if !tail.isEmpty { result.append(SentencePiece(text: tail)) }
        return result.isEmpty ? [SentencePiece(text: raw)] : result
    }

    private static func locateUTF16Range(
        of needle: String,
        in haystack: String,
        from searchFrom: inout String.Index
    ) -> NSRange? {
        if searchFrom > haystack.endIndex { searchFrom = haystack.startIndex }
        if searchFrom < haystack.startIndex { searchFrom = haystack.startIndex }
        if let range = haystack.range(of: needle, range: searchFrom..<haystack.endIndex) {
            searchFrom = range.upperBound
            return NSRange(range, in: haystack)
        }
        if let range = haystack.range(of: needle) {
            searchFrom = range.upperBound
            return NSRange(range, in: haystack)
        }
        return nil
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
