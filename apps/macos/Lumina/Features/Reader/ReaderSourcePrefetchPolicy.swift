import Foundation

/// Keeps original-text fetch fan-out off the scroll / search-next hot path.
/// Large books (thousands of segments) freeze if every `topSegmentIdx` tick or
/// every concurrent `getSegment` completion republishes the whole feed.
enum ReaderSourcePrefetchPolicy {
    /// Delay before neighbour source prefetch after the pinned segment moves.
    static let debounceNanoseconds: UInt64 = 160_000_000
    /// Batch loading/cache publishes so N parallel completions become one paint.
    static let publishCoalesceNanoseconds: UInt64 = 48_000_000

    /// Indices to load around the visible segment (center first, then nearest).
    static func neighbourOrder(center: Int, radius: Int, sortedIdxs: [Int]) -> [Int] {
        guard let pos = sortedIdxs.firstIndex(of: center) else { return [] }
        let start = max(0, pos - radius)
        let end = min(sortedIdxs.count - 1, pos + radius)
        guard start <= end else { return [] }
        return Array(sortedIdxs[start...end])
            .sorted { abs($0 - center) < abs($1 - center) }
    }
}
