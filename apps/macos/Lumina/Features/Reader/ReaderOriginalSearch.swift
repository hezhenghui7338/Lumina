import AppKit
import Foundation

struct OriginalSearchHit: Codable, Equatable, Hashable, Identifiable {
    var id: String { "\(segment_index):\(start_utf16):\(end_utf16)" }
    let segment_index: Int
    let start: Int
    let end: Int
    let start_utf16: Int
    let end_utf16: Int
    let snippet: String
}

struct OriginalSearchResponse: Codable, Equatable {
    let query: String
    let hits: [OriginalSearchHit]
    let truncated: Bool
}

enum OriginalSearchNav: Equatable {
    /// Move highlight within already-loaded hits (may wrap).
    case step(to: Int)
    /// Hits were truncated; fetch the next page after the last loaded hit.
    case loadMore
}

/// How far `locateOriginalSearchHit` must go for the current hit.
enum OriginalSearchLocateKind: Equatable {
    /// Same segment, already in original mode, source cached — only highlight.
    case highlightOnly
    /// Need content-mode / scroll / fetchSource.
    case navigateAndFetch
}

enum OriginalSearchHighlight {
    /// Coalesce rapid ⌘G / next-hit navigations so MainActor is not flooded.
    static let stepCoalesceNanoseconds: UInt64 = 32_000_000

    static func nsRange(
        startUTF16: Int,
        endUTF16: Int,
        inUTF16Length length: Int
    ) -> NSRange? {
        guard startUTF16 >= 0, endUTF16 > startUTF16, endUTF16 <= length else {
            return nil
        }
        return NSRange(location: startUTF16, length: endUTF16 - startUTF16)
    }

    static func range(for hit: OriginalSearchHit, utf16Length: Int) -> NSRange? {
        nsRange(
            startUTF16: hit.start_utf16,
            endUTF16: hit.end_utf16,
            inUTF16Length: utf16Length
        )
    }

    static func steppedIndex(current: Int, delta: Int, count: Int) -> Int? {
        guard count > 0 else { return nil }
        let next = (current + delta) % count
        return next < 0 ? next + count : next
    }

    /// Truncated result sets must not wrap forward: wrapping jumps from a late
    /// hit back to the first and freezes the full-ForEach reader. Load more instead.
    static func navigate(
        current: Int,
        delta: Int,
        count: Int,
        truncated: Bool
    ) -> OriginalSearchNav? {
        guard count > 0 else { return nil }
        if delta > 0, current >= count - 1, truncated {
            return .loadMore
        }
        guard let next = steppedIndex(current: current, delta: delta, count: count) else {
            return nil
        }
        return .step(to: next)
    }

    /// Same-segment next/prev must not re-run navigate + fetchSource (freezes).
    static func locateKind(
        hitSegmentIndex: Int,
        currentSegmentIndex: Int?,
        contentModeIsOriginal: Bool,
        sourceCached: Bool
    ) -> OriginalSearchLocateKind {
        if contentModeIsOriginal,
           currentSegmentIndex == hitSegmentIndex,
           sourceCached
        {
            return .highlightOnly
        }
        return .navigateAndFetch
    }

    static func statusLabel(index: Int, count: Int, truncated: Bool) -> String {
        guard count > 0 else { return "无匹配" }
        let suffix = truncated ? "+" : ""
        return "\(index + 1)/\(count)\(suffix)"
    }

    static func normalizedQuery(_ raw: String) -> String {
        raw.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

extension Notification.Name {
    static let luminaRevealTextRect = Notification.Name("luminaRevealTextRect")
}
