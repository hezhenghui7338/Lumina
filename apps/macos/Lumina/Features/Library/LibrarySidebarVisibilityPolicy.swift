import Foundation

/// Whether the library collection sidebar column should be visible.
/// Browse mode (no book): always shown. Reading never inserts a recents
/// column — recents is a full-page cover over the reader.
enum LibrarySidebarVisibilityPolicy {
    static func showsLibrarySidebar(hasSelectedBook: Bool) -> Bool {
        !hasSelectedBook
    }
}
