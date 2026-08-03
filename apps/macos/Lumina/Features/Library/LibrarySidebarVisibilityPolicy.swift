import Foundation

/// Whether the library sidebar column should be visible.
/// Browse mode (no book): always shown. Reading: only when toolbar-pinned.
enum LibrarySidebarVisibilityPolicy {
    static func showsLibrarySidebar(hasSelectedBook: Bool, pinned: Bool) -> Bool {
        !hasSelectedBook || pinned
    }
}
