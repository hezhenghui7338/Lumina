import CoreGraphics
import SwiftUI

/// Grid bookshelf scroll stability.
///
/// macOS legacy / “always” scrollbars steal ~16pt of *content* width when they
/// appear. Book covers use a 3∶4 aspect ratio of that width, so each card’s
/// height shrinks when the scroller shows — total content height drops below
/// the viewport, the scroller hides, width grows, covers grow, scroller shows
/// again. Summarizing cards sit nearer the overflow edge, so the loop is
/// continuous.
///
/// Fix: derive a **pinned layout width** from the outer container that already
/// reserves the scroller gutter, and lay the grid out at that width only.
/// Scroller show/hide then cannot change cover height.
enum BookshelfGridScrollPolicy {
    static let minItemWidth: CGFloat = 148
    static let columnSpacing: CGFloat = 16
    static let rowSpacing: CGFloat = 20
    static let contentPadding: CGFloat = 20
    /// Typical macOS legacy scroller track.
    static let scrollerGutter: CGFloat = 16

    /// Width available for the card grid after padding **and** a permanent
    /// scroller-gutter reservation. Use this for both column count and the
    /// grid’s explicit `frame(width:)`.
    static func layoutWidth(forContainerWidth width: CGFloat) -> CGFloat {
        max(0, width - contentPadding * 2 - scrollerGutter)
    }

    static func columnCount(forLayoutWidth layoutWidth: CGFloat) -> Int {
        max(1, Int((layoutWidth + columnSpacing) / (minItemWidth + columnSpacing)))
    }

    static func columnCount(forContainerWidth width: CGFloat) -> Int {
        columnCount(forLayoutWidth: layoutWidth(forContainerWidth: width))
    }

    static func gridItems(forLayoutWidth layoutWidth: CGFloat) -> [GridItem] {
        Array(
            repeating: GridItem(.flexible(), spacing: columnSpacing),
            count: columnCount(forLayoutWidth: layoutWidth)
        )
    }

    static func gridItems(forContainerWidth width: CGFloat) -> [GridItem] {
        gridItems(forLayoutWidth: layoutWidth(forContainerWidth: width))
    }

    /// Split a page of books into fixed column rows (eager, not LazyVGrid).
    static func rows<T>(books: [T], columnCount: Int) -> [[T]] {
        let columns = max(1, columnCount)
        var result: [[T]] = []
        var index = 0
        while index < books.count {
            let end = min(index + columns, books.count)
            result.append(Array(books[index..<end]))
            index = end
        }
        return result
    }
}

/// Fixed slots so progress label wrap / meter presence cannot change card
/// height and re-tip the grid over the scroll threshold.
enum BookshelfGridCardMetrics {
    /// Two caption lines (status may include 「摘要 n/m · 段 k · …」).
    static let statusReservedHeight: CGFloat = 32
    /// Small determinate `ProgressView` track.
    static let meterReservedHeight: CGFloat = 8
}
