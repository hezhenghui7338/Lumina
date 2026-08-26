import Foundation

/// Chrome actions that can be contributed by library / reader surfaces. The
/// bookshelf contributes to the window toolbar; the reader carries its own
/// floating chrome (top book bar + bottom function bar). The same action must
/// not appear on more than one visible surface. Reading has no recents list.
enum LibraryChromeAction: String, CaseIterable, Hashable {
    case importBook
    case bookshelf
    case segmentList
    case search
    case allNotes
}

enum LibraryChromeSurface: String, CaseIterable {
    case bookshelf
    case reader
}

enum LibraryChromeActionPolicy {
    static func toolbarActions(on surface: LibraryChromeSurface) -> Set<LibraryChromeAction> {
        switch surface {
        case .bookshelf:
            return [.importBook, .search, .allNotes]
        case .reader:
            // Rendered by the reader's floating chrome, not the window toolbar.
            return [.importBook, .bookshelf, .segmentList]
        }
    }

    static func windowToolbarSurfaces(hasSelectedBook: Bool) -> [LibraryChromeSurface] {
        if !hasSelectedBook {
            return [.bookshelf]
        }
        return [.reader]
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

/// Context-menu actions for a library list/grid row.
enum LibraryBookContextAction: String, CaseIterable, Hashable {
    case favorite
    case rename
    case reclassify
    case startSummarize
    case stopSummarize
    case resegment
    case exportMarkdown
    case delete
}

enum LibraryBookContextMenuPolicy {
    static func actions(for book: BookSummary) -> [LibraryBookContextAction] {
        var items: [LibraryBookContextAction] = [.favorite, .rename, .reclassify]
        if book.canStartSummarize { items.append(.startSummarize) }
        if book.canStopSummarize { items.append(.stopSummarize) }
        items.append(.resegment)
        items.append(.exportMarkdown)
        items.append(.delete)
        return items
    }

    static func isEnabled(_ action: LibraryBookContextAction, for book: BookSummary) -> Bool {
        switch action {
        case .favorite, .rename, .delete:
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
