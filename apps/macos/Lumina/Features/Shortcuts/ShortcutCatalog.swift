import AppKit
import Foundation

enum ShortcutGroup: String, CaseIterable, Identifiable {
    case global
    case reader
    case fixed

    var id: String { rawValue }

    var title: String {
        switch self {
        case .global: return "全局"
        case .reader: return "阅读器"
        case .fixed: return "固定（不可改）"
        }
    }
}

enum ShortcutAction: String, CaseIterable, Identifiable, Codable {
    case globalSearch
    case importBooks
    case toggleContentMode
    case toggleSegmentPanel
    case originalSearch
    case searchNext
    case searchPrev
    case startSummarize
    case stopSummarize
    case openSummarizeMenu
    case regenerateSegment
    case openSegmentMenu
    case adjustBoundary
    case toggleListen
    case toggleSegmentList
    case toggleNotes
    case toggleChat
    case toggleDisplay
    case exportMarkdown
    case backToLibrary
    case prevSegment
    case nextSegment
    case scrollUp
    case scrollDown
    case pageUp
    case pageDown
    case dismissOverlay

    var id: String { rawValue }

    var title: String {
        switch self {
        case .globalSearch: return "跨书搜索"
        case .importBooks: return "导入"
        case .toggleContentMode: return "切换全书摘要/原文"
        case .toggleSegmentPanel: return "当前段切换原文/摘要"
        case .originalSearch: return "书内原文搜索"
        case .searchNext: return "搜索下一条"
        case .searchPrev: return "搜索上一条"
        case .startSummarize: return "开始摘要"
        case .stopSummarize: return "停止摘要"
        case .openSummarizeMenu: return "摘要菜单"
        case .regenerateSegment: return "当前段重新摘要"
        case .openSegmentMenu: return "分段菜单"
        case .adjustBoundary: return "调整分段"
        case .toggleListen: return "听/停"
        case .toggleSegmentList: return "段列表"
        case .toggleNotes: return "笔记"
        case .toggleChat: return "深聊"
        case .toggleDisplay: return "显示"
        case .exportMarkdown: return "导出"
        case .backToLibrary: return "返回书架"
        case .prevSegment: return "上一段"
        case .nextSegment: return "下一段"
        case .scrollUp: return "向上滚动"
        case .scrollDown: return "向下滚动"
        case .pageUp: return "向上翻页"
        case .pageDown: return "向下翻页"
        case .dismissOverlay: return "关闭浮层"
        }
    }

    var detail: String? {
        switch self {
        case .openSummarizeMenu:
            return "只打开顶栏摘要菜单；重新摘要整书须再点菜单项"
        case .openSegmentMenu:
            return "只打开顶栏分段菜单；整书重新分段须再点菜单项"
        case .prevSegment, .nextSegment:
            return "书架翻页使用同键，分属不同界面"
        case .searchNext, .searchPrev:
            return "仅书内搜索栏打开时生效"
        default:
            return nil
        }
    }

    var group: ShortcutGroup {
        switch self {
        case .globalSearch, .importBooks:
            return .global
        case .scrollUp, .scrollDown, .pageUp, .pageDown, .dismissOverlay:
            return .fixed
        default:
            return .reader
        }
    }

    var isCustomizable: Bool { group != .fixed }

    /// Global actions fire outside the reader; reader actions need an open book.
    var isGlobal: Bool {
        switch self {
        case .globalSearch, .importBooks:
            return true
        default:
            return false
        }
    }
}

struct ShortcutModifiers: OptionSet, Codable, Hashable {
    let rawValue: Int

    static let command = ShortcutModifiers(rawValue: 1 << 0)
    static let shift = ShortcutModifiers(rawValue: 1 << 1)
    static let option = ShortcutModifiers(rawValue: 1 << 2)
    static let control = ShortcutModifiers(rawValue: 1 << 3)

    static func from(_ flags: NSEvent.ModifierFlags) -> ShortcutModifiers {
        let device = flags.intersection(.deviceIndependentFlagsMask)
        var mods = ShortcutModifiers()
        if device.contains(.command) { mods.insert(.command) }
        if device.contains(.shift) { mods.insert(.shift) }
        if device.contains(.option) { mods.insert(.option) }
        if device.contains(.control) { mods.insert(.control) }
        return mods
    }

    var nsFlags: NSEvent.ModifierFlags {
        var flags: NSEvent.ModifierFlags = []
        if contains(.command) { flags.insert(.command) }
        if contains(.shift) { flags.insert(.shift) }
        if contains(.option) { flags.insert(.option) }
        if contains(.control) { flags.insert(.control) }
        return flags
    }

    var displayPrefix: String {
        var parts: [String] = []
        if contains(.control) { parts.append("⌃") }
        if contains(.option) { parts.append("⌥") }
        if contains(.shift) { parts.append("⇧") }
        if contains(.command) { parts.append("⌘") }
        return parts.joined()
    }
}

struct ShortcutChord: Codable, Equatable, Hashable {
    /// Hardware key code when the binding is not a printable character (arrows, etc.).
    var keyCode: UInt16?
    /// Lowercased single character for letter / digit / punctuation bindings.
    var character: String?
    var modifiers: ShortcutModifiers

    var display: String {
        let keyLabel: String
        if let character, !character.isEmpty {
            keyLabel = Self.displayCharacter(character)
        } else if let keyCode {
            keyLabel = Self.displayKeyCode(keyCode)
        } else {
            keyLabel = "?"
        }
        return modifiers.displayPrefix + keyLabel
    }

    func matches(_ event: NSEvent) -> Bool {
        let eventMods = ShortcutModifiers.from(event.modifierFlags)
        guard eventMods == modifiers else { return false }

        if let character, !character.isEmpty {
            let ignored = (event.charactersIgnoringModifiers ?? "").lowercased()
            if ignored == character { return true }
            // Period / comma sometimes report empty ignoring-modifiers on some layouts.
            if character == ".", event.keyCode == 47 { return true }
            if character == ",", event.keyCode == 43 { return true }
            if character == "[", event.keyCode == 33 { return true }
            if character == "]", event.keyCode == 30 { return true }
        }
        if let keyCode, event.keyCode == keyCode {
            return true
        }
        return false
    }

    static func from(event: NSEvent) -> ShortcutChord? {
        let mods = ShortcutModifiers.from(event.modifierFlags)
        let keyCode = event.keyCode

        switch keyCode {
        case 123, 124, 125, 126, 116, 121, 53: // arrows, page, escape
            return ShortcutChord(keyCode: keyCode, character: nil, modifiers: mods)
        default:
            break
        }

        let raw = (event.charactersIgnoringModifiers ?? "").lowercased()
        guard raw.count == 1, let ch = raw.first, ch.isASCII else {
            // Fallback for period when characters are empty.
            if keyCode == 47 {
                return ShortcutChord(keyCode: keyCode, character: ".", modifiers: mods)
            }
            if keyCode == 33 {
                return ShortcutChord(keyCode: keyCode, character: "[", modifiers: mods)
            }
            return nil
        }
        if ch == "\u{1b}" { // escape
            return ShortcutChord(keyCode: 53, character: nil, modifiers: mods)
        }
        return ShortcutChord(keyCode: keyCode, character: String(ch), modifiers: mods)
    }

    private static func displayCharacter(_ character: String) -> String {
        switch character {
        case " ": return "空格"
        case ".": return "."
        default: return character.uppercased()
        }
    }

    private static func displayKeyCode(_ keyCode: UInt16) -> String {
        switch keyCode {
        case 123: return "←"
        case 124: return "→"
        case 126: return "↑"
        case 125: return "↓"
        case 116: return "PgUp"
        case 121: return "PgDn"
        case 53: return "Esc"
        case 36: return "↩"
        case 48: return "⇥"
        case 49: return "空格"
        default: return "Key\(keyCode)"
        }
    }
}

enum ShortcutCatalog {
    static let allActions: [ShortcutAction] = ShortcutAction.allCases

    static let customizableActions: [ShortcutAction] = allActions.filter(\.isCustomizable)

    static let defaults: [ShortcutAction: ShortcutChord] = [
        // Global: keep familiar ⌘+letter (2 keys)
        .globalSearch: .init(keyCode: 40, character: "k", modifiers: .command),
        .importBooks: .init(keyCode: 31, character: "o", modifiers: .command),
        // Reader: prefer bare keys; otherwise ⌘+letter (avoid ⌘⇧ / ⌘⌥)
        .toggleContentMode: .init(keyCode: 31, character: "o", modifiers: []),
        .toggleSegmentPanel: .init(keyCode: 17, character: "t", modifiers: []),
        .originalSearch: .init(keyCode: 3, character: "f", modifiers: .command),
        .searchNext: .init(keyCode: 5, character: "g", modifiers: .command),
        .searchPrev: .init(keyCode: 32, character: "u", modifiers: .command),
        .startSummarize: .init(keyCode: 15, character: "r", modifiers: []),
        .stopSummarize: .init(keyCode: 47, character: ".", modifiers: .command),
        .openSummarizeMenu: .init(keyCode: 46, character: "m", modifiers: []),
        .regenerateSegment: .init(keyCode: 32, character: "u", modifiers: []),
        .openSegmentMenu: .init(keyCode: 35, character: "p", modifiers: []),
        .adjustBoundary: .init(keyCode: 11, character: "b", modifiers: []),
        .toggleListen: .init(keyCode: 37, character: "l", modifiers: []),
        .toggleSegmentList: .init(keyCode: 18, character: "1", modifiers: []),
        .toggleNotes: .init(keyCode: 19, character: "2", modifiers: []),
        .toggleChat: .init(keyCode: 20, character: "3", modifiers: []),
        .toggleDisplay: .init(keyCode: 21, character: "4", modifiers: []),
        .exportMarkdown: .init(keyCode: 14, character: "e", modifiers: .command),
        .backToLibrary: .init(keyCode: 33, character: "[", modifiers: .command),
        .prevSegment: .init(keyCode: 123, character: nil, modifiers: []),
        .nextSegment: .init(keyCode: 124, character: nil, modifiers: []),
        .scrollUp: .init(keyCode: 126, character: nil, modifiers: []),
        .scrollDown: .init(keyCode: 125, character: nil, modifiers: []),
        .pageUp: .init(keyCode: 116, character: nil, modifiers: []),
        .pageDown: .init(keyCode: 121, character: nil, modifiers: []),
        .dismissOverlay: .init(keyCode: 53, character: nil, modifiers: []),
    ]

    static func defaultChord(for action: ShortcutAction) -> ShortcutChord {
        defaults[action]!
    }

    /// System / app-reserved chords that must not be assigned.
    static let reservedChords: [ShortcutChord] = [
        .init(keyCode: 12, character: "q", modifiers: .command),
        .init(keyCode: 13, character: "w", modifiers: .command),
        .init(keyCode: 4, character: "h", modifiers: .command),
        .init(keyCode: 46, character: "m", modifiers: .command),
        .init(keyCode: 48, character: nil, modifiers: .command), // ⌘Tab
        .init(keyCode: 49, character: " ", modifiers: .command), // ⌘Space
    ]

    static func isReserved(_ chord: ShortcutChord) -> Bool {
        reservedChords.contains { reserved in
            chordsConflict(reserved, chord)
        }
    }

    static func chordsConflict(_ a: ShortcutChord, _ b: ShortcutChord) -> Bool {
        guard a.modifiers == b.modifiers else { return false }
        if let ac = a.character, let bc = b.character, !ac.isEmpty, !bc.isEmpty {
            return ac == bc
        }
        if let ak = a.keyCode, let bk = b.keyCode {
            return ak == bk
        }
        // Character vs keyCode for the same physical key (e.g. period).
        if let ac = a.character, let bk = b.keyCode {
            return keyCode(forCharacter: ac) == bk
        }
        if let bc = b.character, let ak = a.keyCode {
            return keyCode(forCharacter: bc) == ak
        }
        return false
    }

    private static func keyCode(forCharacter character: String) -> UInt16? {
        switch character {
        case ".": return 47
        case ",": return 43
        case "[": return 33
        case "]": return 30
        case " ": return 49
        default: return nil
        }
    }
}
