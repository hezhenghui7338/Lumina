import Foundation

/// Decides how Finder「打开方式」/ dock reopen should surface the single main UI.
enum MainWindowRevealPolicy {
    static let mainWindowId = "main"
    static let urlScheme = "lumina"
    /// Opened when no AppKit window exists so WindowGroup can materialize a scene.
    static let revealURL = URL(string: "lumina://reveal")!

    enum Action: Equatable {
        /// Deminiaturize + makeKeyAndOrderFront existing AppKit windows.
        case orderFrontExisting
        /// Ask SwiftUI to (re)create the main scene (`openWindow` and/or reveal URL).
        case requestOpenMainWindow
    }

    enum RevealStep: Equatable {
        /// Close a stuck help-tag panel (`.help()` / tooltip).
        case dismissHelpTag
        /// Bring a real app window forward and make it key.
        case orderFront
    }

    struct WindowState: Equatable {
        var isVisible: Bool
        var isMiniaturized: Bool
        /// AppKit tooltip / help-tag panel, e.g. `_NSTooltipPanel`.
        var isHelpTag: Bool
        /// `NSPanel` (popover, save panel). Ordered front but not made key after tooltips.
        var isPanel: Bool

        init(
            isVisible: Bool,
            isMiniaturized: Bool,
            isHelpTag: Bool = false,
            isPanel: Bool = false
        ) {
            self.isVisible = isVisible
            self.isMiniaturized = isMiniaturized
            self.isHelpTag = isHelpTag
            self.isPanel = isPanel
        }
    }

    /// `_NSTooltipPanel` and SwiftUI `.help()` hosts. Matching is case-insensitive
    /// so both `Tooltip` and `ToolTip` spellings count.
    static func isHelpTagWindow(className: String) -> Bool {
        className.lowercased().contains("tooltip")
    }

    static func countsAsMainWindow(_ state: WindowState) -> Bool {
        !state.isHelpTag && (state.isVisible || state.isMiniaturized)
    }

    static func action(for windows: [WindowState]) -> Action {
        windows.contains(where: countsAsMainWindow) ? .orderFrontExisting : .requestOpenMainWindow
    }

    /// Help tags are always dismissed. A leftover tooltip must not be ordered
    /// front: `makeKeyAndOrderFront` on it pins the last `.help()` string
    /// (「点击预览新分界」) on screen after Finder「打开方式」.
    static func revealStep(for state: WindowState) -> RevealStep? {
        if state.isHelpTag { return .dismissHelpTag }
        if state.isVisible || state.isMiniaturized { return .orderFront }
        return nil
    }

    /// Second-instance handoff must always ask the running app to show UI,
    /// even when the path list is empty (activate alone is not enough).
    static func shouldPostRevealWithForwardedPaths(_ paths: [String]) -> Bool {
        true
    }

    static func isRevealURL(_ url: URL) -> Bool {
        url.scheme?.lowercased() == urlScheme
    }

    static func distributedUserInfo(paths: [String], reveal: Bool) -> [String: Any] {
        var info: [String: Any] = ["paths": paths]
        if reveal {
            info["reveal"] = true
        }
        return info
    }
}
