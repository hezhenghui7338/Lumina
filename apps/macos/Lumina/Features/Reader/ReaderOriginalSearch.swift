import AppKit
import Foundation
import SwiftUI

struct OriginalSearchHit: Codable, Equatable, Hashable, Identifiable {
    var id: String { "\(segment_index):\(start_utf16):\(end_utf16)" }
    let segment_index: Int
    let start: Int
    let end: Int
    let start_utf16: Int
    let end_utf16: Int
    let snippet: String
    let segment_label: String?
}

struct OriginalSearchResponse: Codable, Equatable {
    let query: String
    let hits: [OriginalSearchHit]
    let truncated: Bool
    let index_ready: Bool?

    init(
        query: String,
        hits: [OriginalSearchHit],
        truncated: Bool,
        index_ready: Bool? = nil
    ) {
        self.query = query
        self.hits = hits
        self.truncated = truncated
        self.index_ready = index_ready
    }
}

enum OriginalSearchPhase: Equatable {
    /// Hit rows with context; no auto-jump.
    case list
    /// Focus feed on the selected hit; bottom bar for back / prev / next.
    case reading
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
    /// Far-apart TOC hits (e.g. `# [§曾国藩全集` every ~300 segs) need enough
    /// delay that only the last target is materialized.
    static let stepCoalesceNanoseconds: UInt64 = 150_000_000
    /// After a search jump, keep suppressing neighbour prefetch / onAppear fan-out.
    static let seekPrefetchSuppressNanoseconds: UInt64 = 280_000_000

    /// While reading a selected hit, render only that segment so far jumps never
    /// drive scrollPosition across the full catalog ForEach.
    static func usesFocusFeed(
        expanded: Bool,
        hitCount: Int,
        phase: OriginalSearchPhase
    ) -> Bool {
        expanded && hitCount > 0 && phase == .reading
    }

    static func showsHitList(
        expanded: Bool,
        phase: OriginalSearchPhase,
        hasSubmittedQuery: Bool
    ) -> Bool {
        expanded && phase == .list && hasSubmittedQuery
    }

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

    /// Neighbour onAppear / visible prefetch must stay off while seeking a hit.
    static func allowsNeighbourSourceFetch(
        seekTarget: Int?,
        segmentIndex: Int
    ) -> Bool {
        guard let seekTarget else { return true }
        return seekTarget == segmentIndex
    }

    static func statusLabel(index: Int, count: Int, truncated: Bool) -> String {
        guard count > 0 else { return "无匹配" }
        let suffix = truncated ? "+" : ""
        return "\(index + 1)/\(count)\(suffix)"
    }

    static func listStatusLabel(count: Int, truncated: Bool) -> String {
        guard count > 0 else { return "无匹配" }
        return truncated ? "\(count)+" : "\(count)"
    }

    static func normalizedQuery(_ raw: String) -> String {
        raw.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// Render API snippets whose match is wrapped in `[…]`.
    static func snippetAttributed(_ snippet: String) -> AttributedString {
        var result = AttributedString()
        var remaining = snippet[...]
        while let open = remaining.firstIndex(of: "["),
              let close = remaining[open...].firstIndex(of: "]"),
              close > open
        {
            let before = remaining[..<open]
            if !before.isEmpty {
                result.append(AttributedString(String(before)))
            }
            let matchStart = remaining.index(after: open)
            let match = remaining[matchStart..<close]
            if !match.isEmpty {
                var attr = AttributedString(String(match))
                attr.backgroundColor = Color.yellow.opacity(0.45)
                attr.foregroundColor = Color.primary
                result.append(attr)
            }
            remaining = remaining[remaining.index(after: close)...]
        }
        if !remaining.isEmpty {
            result.append(AttributedString(String(remaining)))
        }
        return result
    }
}

extension Notification.Name {
    static let luminaRevealTextRect = Notification.Name("luminaRevealTextRect")
}
