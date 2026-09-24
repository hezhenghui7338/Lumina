import CoreGraphics
import Foundation

enum SegmentOutlinePolicy {
    static let ungroupedKey = ""
    static let ungroupedTitle = "未分章"
    static let indentStep: CGFloat = 12
    static let keySeparator = "/"
    /// Title headers shown in the segment list (segment leaf is one more level).
    static let maxTitleDepth = 2

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
        }
        return parts
    }

    static func resolvePath(_ segment: SegmentRow) -> [String] {
        let stored = (segment.heading_path ?? [])
            .map { stripSectionMark($0) }
            .filter { !$0.isEmpty }
        if !stored.isEmpty { return stored }
        return fromChapter(segment.chapter)
    }

    /// Cap heading path at two title levels for list display (PRD).
    /// Deeper titles are not merged into L2 — they belong in segment `label`.
    /// Consecutive duplicate titles collapse to one. 《曾国藩全集N》 prefers year as L2.
    static func displayPath(_ path: [String]) -> [String] {
        let cleaned = dedupeConsecutive(
            path.map { stripSectionMark($0) }.filter { !$0.isEmpty }
        )
        guard let root = cleaned.first else { return [] }
        if isZengVolumeRoot(root) {
            return compressZengDisplayPath(cleaned)
        }
        // Prefer 部分 → 章 when both present (tech books); else 章 → 节.
        if let partIdx = cleaned.firstIndex(where: isPartHeading),
           let chapterIdx = cleaned.firstIndex(where: isChapterHeading),
           chapterIdx > partIdx {
            return [cleaned[partIdx], cleaned[chapterIdx]]
        }
        if let chapterIdx = cleaned.firstIndex(where: isChapterHeading) {
            let chapter = cleaned[chapterIdx]
            let rest = Array(cleaned[(chapterIdx + 1)...])
            if rest.isEmpty { return [chapter] }
            let section = rest.first(where: { numberedSectionDepth($0) == 2 }) ?? rest[0]
            return [chapter, section]
        }
        if cleaned.count <= maxTitleDepth { return cleaned }
        return Array(cleaned.prefix(maxTitleDepth))
    }

    private static func dedupeConsecutive(_ titles: [String]) -> [String] {
        var out: [String] = []
        for title in titles {
            if out.last != title { out.append(title) }
        }
        return out
    }

    private static let partHeading = try! NSRegularExpression(
        pattern: #"^第\s*[0-9一二三四五六七八九十百零〇两]+\s*部分"#
    )
    private static let chapterHeading = try! NSRegularExpression(
        pattern: #"^第\s*[0-9一二三四五六七八九十百零〇两]+\s*章"#
    )
    private static let numberedSection = try! NSRegularExpression(
        pattern: #"^(\d+(?:\.\d+)+)\b"#
    )

    static func isPartHeading(_ title: String) -> Bool {
        let name = stripSectionMark(title)
        guard !name.isEmpty else { return false }
        let range = NSRange(name.startIndex..<name.endIndex, in: name)
        return partHeading.firstMatch(in: name, options: [], range: range) != nil
    }

    static func isChapterHeading(_ title: String) -> Bool {
        let name = stripSectionMark(title)
        guard !name.isEmpty else { return false }
        let range = NSRange(name.startIndex..<name.endIndex, in: name)
        return chapterHeading.firstMatch(in: name, options: [], range: range) != nil
    }

    static func numberedSectionDepth(_ title: String) -> Int? {
        let name = stripSectionMark(title)
        guard !name.isEmpty else { return nil }
        let range = NSRange(name.startIndex..<name.endIndex, in: name)
        guard let match = numberedSection.firstMatch(in: name, options: [], range: range),
              let swiftRange = Range(match.range(at: 1), in: name)
        else { return nil }
        return name[swiftRange].split(separator: ".").count
    }

    private static let zengVolumeRoot = try! NSRegularExpression(
        pattern: #"^曾国藩全集\d+$"#
    )
    private static let yearCore = try! NSRegularExpression(
        pattern: #"^(?:明|清|道光|咸丰|同治|光绪|宣统|顺治|康熙|雍正|乾隆|嘉庆)(?:元|[一二三四五六七八九十百零〇两]+|\d+)年"#
    )

    static func isZengVolumeRoot(_ title: String) -> Bool {
        let name = stripSectionMark(title)
        guard !name.isEmpty else { return false }
        let range = NSRange(name.startIndex..<name.endIndex, in: name)
        return zengVolumeRoot.firstMatch(in: name, options: [], range: range) != nil
    }

    static func yearCoreTitle(_ title: String) -> String? {
        let name = stripSectionMark(title)
        guard !name.isEmpty else { return nil }
        let range = NSRange(name.startIndex..<name.endIndex, in: name)
        guard let match = yearCore.firstMatch(in: name, options: [], range: range),
              let swiftRange = Range(match.range, in: name)
        else { return nil }
        return String(name[swiftRange])
    }

    static func compressZengDisplayPath(_ path: [String]) -> [String] {
        let cleaned = path.map { stripSectionMark($0) }.filter { !$0.isEmpty }
        guard let root = cleaned.first, isZengVolumeRoot(root) else { return cleaned }
        if cleaned.count == 1 { return [root] }
        for title in cleaned.dropFirst() {
            if let year = yearCoreTitle(title) {
                return [root, year]
            }
        }
        return [root, cleaned[1]]
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
        let resolved = displayPath(resolvePath(segment))
        let parts = resolved.isEmpty ? [ungroupedKey] : resolved
        return ancestorKeys(parts)
    }

    /// Every foldable header key for the current catalog (display-depth capped).
    static func allFoldableKeys(in segments: [SegmentRow]) -> Set<String> {
        guard shouldGroup(segments) else { return [] }
        var keys: Set<String> = []
        for segment in segments {
            let resolved = displayPath(resolvePath(segment))
            let parts = resolved.isEmpty ? [ungroupedKey] : resolved
            for key in ancestorKeys(parts) {
                keys.insert(key)
            }
        }
        return keys
    }

    /// Fully collapsed when every foldable header is in `collapsed`.
    static func isFullyCollapsed(collapsed: Set<String>, foldableKeys: Set<String>) -> Bool {
        !foldableKeys.isEmpty && foldableKeys.isSubset(of: collapsed)
    }

    enum BulkToggleAction {
        case expandAll
        case collapseAll
    }

    /// Toggle affordance: expand when already fully collapsed; otherwise collapse all.
    static func bulkToggleAction(
        collapsed: Set<String>,
        foldableKeys: Set<String>
    ) -> BulkToggleAction? {
        guard !foldableKeys.isEmpty else { return nil }
        return isFullyCollapsed(collapsed: collapsed, foldableKeys: foldableKeys)
            ? .expandAll
            : .collapseAll
    }

    static func applyingBulkToggle(
        collapsed: Set<String>,
        foldableKeys: Set<String>
    ) -> Set<String> {
        switch bulkToggleAction(collapsed: collapsed, foldableKeys: foldableKeys) {
        case .none:
            return collapsed
        case .expandAll:
            return []
        case .collapseAll:
            return foldableKeys
        }
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
            let resolved = displayPath(resolvePath(segment))
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
                    // Include the first leaf idx under this emission so the same
                    // pathKey can reappear (mis-ordered years) without duplicate
                    // ForEach ids — LazyVStack treats collisions as blank gaps.
                    rows.append(
                        Row(
                            id: "h:\(key)#\(segment.idx)",
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

    /// Patch a visible leaf row's segment payload without rebuilding the chapter tree.
    /// Returns `false` when the segment is not in `rows` (e.g. under a collapsed header).
    @discardableResult
    static func replaceSegment(_ segment: SegmentRow, in rows: inout [Row]) -> Bool {
        guard let index = rows.firstIndex(where: { !$0.isHeader && $0.segment?.idx == segment.idx })
        else { return false }
        let old = rows[index]
        rows[index] = Row(
            id: old.id,
            isHeader: false,
            pathKey: old.pathKey,
            depth: old.depth,
            title: old.title,
            isCollapsed: old.isCollapsed,
            headerCount: old.headerCount,
            grouped: old.grouped,
            segment: segment
        )
        return true
    }

    /// Chapter / heading tree identity — when these change, callers must full-rebuild.
    static func structureChanged(from old: SegmentRow, to new: SegmentRow) -> Bool {
        old.chapter != new.chapter || old.heading_path != new.heading_path
    }
}
