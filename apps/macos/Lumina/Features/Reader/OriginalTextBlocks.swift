import CoreGraphics
import Foundation

/// Parsed pipe/GFM table for original-text grid rendering.
struct OriginalPipeTable: Equatable {
    var header: [String]?
    var rows: [[String]]

    var columnCount: Int {
        let fromHeader = header?.count ?? 0
        let fromRows = rows.map(\.count).max() ?? 0
        return max(fromHeader, fromRows)
    }
}

/// Reading-body fragments after illustration offsets + table detection.
enum OriginalTextBlock: Equatable {
    case text(String)
    case table(OriginalPipeTable)
    case image(SegmentIllustration)
}

enum OriginalIllustrationLayoutPolicy {
    /// Cap illustration height so a tall figure does not dominate the feed.
    static let maxHeight: CGFloat = 420
    static let verticalPadding: CGFloat = 8

    static func aspectRatio(width: Int?, height: Int?) -> CGFloat? {
        guard let width, let height, width > 0, height > 0 else { return nil }
        return CGFloat(width) / CGFloat(height)
    }
}

enum OriginalTextBlockLayout {
    /// Illustration split first, then pipe/GFM (and legacy ` | `) tables inside text.
    static func parts(
        text: String,
        illustrations: [SegmentIllustration]
    ) -> [OriginalTextBlock] {
        let illusParts = OriginalTextIllustrationLayout.parts(
            text: text,
            illustrations: illustrations
        )
        var result: [OriginalTextBlock] = []
        for part in illusParts {
            switch part {
            case .text(let chunk):
                result.append(contentsOf: parseTextAndTables(chunk))
            case .image(let illustration):
                result.append(.image(illustration))
            }
        }
        return mergeAdjacentText(result)
    }

    /// Detect GFM / legacy pipe tables inside a single text chunk.
    static func parseTextAndTables(_ text: String) -> [OriginalTextBlock] {
        guard !text.isEmpty else { return [] }
        let lines = text.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
        var blocks: [OriginalTextBlock] = []
        var prose: [String] = []
        var i = 0

        func flushProse() {
            let joined = prose.joined(separator: "\n")
            if !joined.isEmpty {
                blocks.append(.text(joined))
            }
            prose.removeAll(keepingCapacity: true)
        }

        while i < lines.count {
            if let table = consumeTable(lines: lines, start: i) {
                flushProse()
                blocks.append(.table(table.table))
                i = table.end
                continue
            }
            prose.append(lines[i])
            i += 1
        }
        flushProse()
        return blocks
    }

    private static func mergeAdjacentText(_ blocks: [OriginalTextBlock]) -> [OriginalTextBlock] {
        var merged: [OriginalTextBlock] = []
        for block in blocks {
            if case .text(let next) = block,
               case .text(let prev) = merged.last {
                merged[merged.count - 1] = .text(prev + next)
            } else if case .text(let t) = block, t.isEmpty {
                continue
            } else {
                merged.append(block)
            }
        }
        return merged
    }

    private static func consumeTable(
        lines: [String],
        start: Int
    ) -> (table: OriginalPipeTable, end: Int)? {
        guard start < lines.count else { return nil }
        let first = lines[start]
        if isGFMRow(first) {
            return consumeGFMTable(lines: lines, start: start)
        }
        if isLegacyPipeRow(first) {
            return consumeLegacyTable(lines: lines, start: start)
        }
        return nil
    }

    private static func consumeGFMTable(
        lines: [String],
        start: Int
    ) -> (table: OriginalPipeTable, end: Int)? {
        var i = start
        var rawRows: [[String]] = []
        var sawSeparator = false
        while i < lines.count {
            let line = lines[i]
            if line.trimmingCharacters(in: .whitespaces).isEmpty {
                break
            }
            if isGFMSeparator(line) {
                sawSeparator = true
                i += 1
                continue
            }
            guard isGFMRow(line) else { break }
            rawRows.append(parseGFMCells(line))
            i += 1
        }
        guard !rawRows.isEmpty else { return nil }
        // Single orphan GFM row without separator or follow-up is still a table
        // (new DOCX/HTML single-row tables emit header + separator).
        if rawRows.count == 1 && !sawSeparator && i == start + 1 {
            // Keep as table only when it looks multi-column.
            guard rawRows[0].count >= 2 else { return nil }
        }
        let table: OriginalPipeTable
        if sawSeparator, !rawRows.isEmpty {
            table = OriginalPipeTable(header: rawRows[0], rows: Array(rawRows.dropFirst()))
        } else if rawRows.count >= 2 {
            table = OriginalPipeTable(header: rawRows[0], rows: Array(rawRows.dropFirst()))
        } else {
            table = OriginalPipeTable(header: nil, rows: rawRows)
        }
        return (table, i)
    }

    private static func consumeLegacyTable(
        lines: [String],
        start: Int
    ) -> (table: OriginalPipeTable, end: Int)? {
        let firstCells = parseLegacyCells(lines[start])
        guard firstCells.count >= 2 else { return nil }
        var i = start + 1
        var rawRows: [[String]] = [firstCells]
        while i < lines.count {
            let line = lines[i]
            if line.trimmingCharacters(in: .whitespaces).isEmpty {
                break
            }
            if isGFMRow(line) || isGFMSeparator(line) {
                break
            }
            guard isLegacyPipeRow(line) else { break }
            let cells = parseLegacyCells(line)
            guard cells.count == firstCells.count else { break }
            rawRows.append(cells)
            i += 1
        }
        // Need at least two rows so prose like "a | b" alone is not a table.
        guard rawRows.count >= 2 else { return nil }
        return (
            OriginalPipeTable(header: rawRows[0], rows: Array(rawRows.dropFirst())),
            i
        )
    }

    private static func isGFMRow(_ line: String) -> Bool {
        let trimmed = line.trimmingCharacters(in: .whitespaces)
        guard trimmed.hasPrefix("|"), trimmed.hasSuffix("|"), trimmed.count >= 3 else {
            return false
        }
        return !isGFMSeparator(trimmed)
    }

    private static func isGFMSeparator(_ line: String) -> Bool {
        let trimmed = line.trimmingCharacters(in: .whitespaces)
        guard trimmed.contains("-") else { return false }
        let inner = trimmed.trimmingCharacters(in: CharacterSet(charactersIn: "|"))
        let parts = inner.split(separator: "|", omittingEmptySubsequences: false)
        guard !parts.isEmpty else { return false }
        return parts.allSatisfy { part in
            let cell = part.trimmingCharacters(in: .whitespaces)
            guard !cell.isEmpty else { return false }
            return cell.allSatisfy { $0 == "-" || $0 == ":" }
        }
    }

    private static func isLegacyPipeRow(_ line: String) -> Bool {
        let trimmed = line.trimmingCharacters(in: .whitespaces)
        guard !trimmed.hasPrefix("|") else { return false }
        return trimmed.contains(" | ")
    }

    private static func parseGFMCells(_ line: String) -> [String] {
        var trimmed = line.trimmingCharacters(in: .whitespaces)
        if trimmed.hasPrefix("|") { trimmed.removeFirst() }
        if trimmed.hasSuffix("|") { trimmed.removeLast() }
        return splitPipeCells(trimmed)
    }

    private static func parseLegacyCells(_ line: String) -> [String] {
        splitPipeCells(line.trimmingCharacters(in: .whitespaces))
    }

    private static func splitPipeCells(_ body: String) -> [String] {
        var cells: [String] = []
        var current = ""
        var i = body.startIndex
        while i < body.endIndex {
            let ch = body[i]
            if ch == "\\" {
                let next = body.index(after: i)
                if next < body.endIndex, body[next] == "|" {
                    current.append("|")
                    i = body.index(after: next)
                    continue
                }
            }
            if ch == "|" {
                cells.append(current.trimmingCharacters(in: .whitespaces))
                current = ""
                i = body.index(after: i)
                continue
            }
            current.append(ch)
            i = body.index(after: i)
        }
        cells.append(current.trimmingCharacters(in: .whitespaces))
        return cells
    }
}
