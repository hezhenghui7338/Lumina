import CoreGraphics
import Foundation

enum SegmentOutlinePolicy {
    static let ungroupedKey = ""
    static let ungroupedTitle = "未分章"
    static let indentStep: CGFloat = 12
    static let keySeparator = "/"

    struct Row: Identifiable, Equatable {
        let id: String
        let isHeader: Bool
        let pathKey: String
        let depth: Int
        let title: String
        let isCollapsed: Bool
        let headerCount: Int
        let grouped: Bool
        let segment: SegmentRow?

        var idx: Int? { segment?.idx }
    }

    static func stripSectionMark(_ raw: String) -> String {
        var text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        while text.hasPrefix("§") {
            text.removeFirst()
            text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        while text.hasSuffix("§") {
            text.removeLast()
            text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return text
    }

    static func fromChapter(_ chapter: String?) -> [String] {
        let name = stripSectionMark(chapter ?? "")
        guard !name.isEmpty else { return [] }
        var parts: [String] = []
        for piece in name.split(separator: "·", omittingEmptySubsequences: true) {
            let cleaned = stripSectionMark(String(piece))
            if !cleaned.isEmpty { parts.append(cleaned) }
            if parts.count >= 2 { break }
        }
        return parts
    }

    static func resolvePath(_ segment: SegmentRow) -> [String] {
        let stored = (segment.heading_path ?? [])
            .map { stripSectionMark($0) }
            .filter { !$0.isEmpty }
        if !stored.isEmpty { return Array(stored.prefix(2)) }
        return fromChapter(segment.chapter)
    }

    static func pathKey(_ parts: [String]) -> String {
        parts.joined(separator: keySeparator)
    }

    static func ancestorKeys(_ parts: [String]) -> [String] {
        var acc: [String] = []
        var keys: [String] = []
        for part in parts {
            acc.append(part)
            keys.append(pathKey(acc))
        }
        return keys
    }

    static func shouldGroup(_ segments: [SegmentRow]) -> Bool {
        segments.contains { !resolvePath($0).isEmpty }
    }

    static func keysToReveal(for idx: Int, in segments: [SegmentRow]) -> [String] {
        guard shouldGroup(segments),
              let segment = segments.first(where: { $0.idx == idx })
        else { return [] }
        let resolved = resolvePath(segment)
        let parts = resolved.isEmpty ? [ungroupedKey] : resolved
        return ancestorKeys(parts)
    }

    static func build(segments: [SegmentRow], collapsed: Set<String>) -> [Row] {
        if segments.isEmpty { return [] }
        if !shouldGroup(segments) {
            return segments.map { segment in
                Row(
                    id: "s:\(segment.idx)",
                    isHeader: false,
                    pathKey: "",
                    depth: 0,
                    title: "",
                    isCollapsed: false,
                    headerCount: 0,
                    grouped: false,
                    segment: segment
                )
            }
        }

        var counts: [String: Int] = [:]
        let displayed = segments.map { segment -> (parts: [String], titles: [String]) in
            let resolved = resolvePath(segment)
            if resolved.isEmpty {
                return ([ungroupedKey], [ungroupedTitle])
            }
            return (resolved, resolved)
        }
        for item in displayed {
            var acc: [String] = []
            for part in item.parts {
                acc.append(part)
                counts[pathKey(acc), default: 0] += 1
            }
        }

        func isCollapsedPrefix(_ parts: [String]) -> Bool {
            var acc: [String] = []
            for part in parts {
                acc.append(part)
                if collapsed.contains(pathKey(acc)) { return true }
            }
            return false
        }

        var rows: [Row] = []
        var openPath: [String] = []
        for (segment, item) in zip(segments, displayed) {
            let path = item.parts
            let titles = item.titles
            var common = 0
            while common < min(openPath.count, path.count), openPath[common] == path[common] {
                common += 1
            }
            openPath = Array(openPath.prefix(common))

            var skipChildren = common > 0 && isCollapsedPrefix(Array(path.prefix(common)))
            if !skipChildren {
                if common > 0, collapsed.contains(pathKey(Array(path.prefix(common)))) {
                    skipChildren = true
                }
            }
            if !skipChildren {
                for index in common..<path.count {
                    let prefix = Array(path.prefix(index + 1))
                    if index > 0, isCollapsedPrefix(Array(prefix.dropLast())) {
                        skipChildren = true
                        break
                    }
                    let key = pathKey(prefix)
                    let collapsedNow = collapsed.contains(key)
                    rows.append(
                        Row(
                            id: "h:\(key)",
                            isHeader: true,
                            pathKey: key,
                            depth: index,
                            title: titles[index],
                            isCollapsed: collapsedNow,
                            headerCount: counts[key] ?? 0,
                            grouped: true,
                            segment: nil
                        )
                    )
                    openPath.append(path[index])
                    if collapsedNow {
                        skipChildren = true
                        break
                    }
                }
            }
            if !skipChildren {
                rows.append(
                    Row(
                        id: "s:\(segment.idx)",
                        isHeader: false,
                        pathKey: pathKey(path),
                        depth: path.count,
                        title: "",
                        isCollapsed: false,
                        headerCount: 0,
                        grouped: true,
                        segment: segment
                    )
                )
            }
        }
        return rows
    }
}
