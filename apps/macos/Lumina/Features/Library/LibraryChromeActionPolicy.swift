import Foundation

/// Window-toolbar actions that can be contributed by library / reader surfaces.
/// Sibling `NavigationStack`s on macOS merge into one window toolbar, so the
/// same action must not appear on more than one visible surface.
enum LibraryChromeAction: String, CaseIterable, Hashable {
    case importBook
    case bookshelf
    case recents
    case segmentList
    case search
    case allNotes
}

enum LibraryChromeSurface: String, CaseIterable {
    case bookshelf
    case recentsSidebar
    case reader
}

enum LibraryChromeActionPolicy {
    static func toolbarActions(on surface: LibraryChromeSurface) -> Set<LibraryChromeAction> {
        switch surface {
        case .bookshelf:
            return [.importBook, .search, .allNotes]
        case .recentsSidebar:
            // List-only while reading. Any toolbar here duplicates Reader chrome.
            return []
        case .reader:
            return [.importBook, .bookshelf, .recents, .segmentList]
        }
    }

    static func windowToolbarSurfaces(
        hasSelectedBook: Bool,
        recentsPinned: Bool
    ) -> [LibraryChromeSurface] {
        if !hasSelectedBook {
            return [.bookshelf]
        }
        var surfaces: [LibraryChromeSurface] = [.reader]
        if recentsPinned {
            surfaces.append(.recentsSidebar)
        }
        return surfaces
    }

    static func duplicateActions(
        among surfaces: [LibraryChromeSurface]
    ) -> Set<LibraryChromeAction> {
        var seen = Set<LibraryChromeAction>()
        var duplicates = Set<LibraryChromeAction>()
        for surface in surfaces {
            for action in toolbarActions(on: surface) {
                if !seen.insert(action).inserted {
                    duplicates.insert(action)
                }
            }
        }
        return duplicates
    }
}

/// Context-menu actions for a library list/grid/recents row.
enum LibraryBookContextAction: String, CaseIterable, Hashable {
    case favorite
    case reclassify
    case startSummarize
    case stopSummarize
    case resegment
    case exportMarkdown
    case delete
}

enum LibraryBookContextMenuPolicy {
    static func actions(for book: BookSummary) -> [LibraryBookContextAction] {
        var items: [LibraryBookContextAction] = [.favorite, .reclassify]
        if book.canStartSummarize { items.append(.startSummarize) }
        if book.canStopSummarize { items.append(.stopSummarize) }
        items.append(.resegment)
        items.append(.exportMarkdown)
        items.append(.delete)
        return items
    }

    static func isEnabled(_ action: LibraryBookContextAction, for book: BookSummary) -> Bool {
        switch action {
        case .favorite, .delete:
            return true
        case .reclassify:
            return !book.isProcessing
        case .startSummarize:
            return book.canStartSummarize
        case .stopSummarize:
            return book.canStopSummarize
        case .resegment:
            return book.canResegment
        case .exportMarkdown:
            return book.summaryReady > 0
        }
    }
}
