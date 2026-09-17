import AppKit
import Combine
import Foundation

enum ShortcutBindResult: Equatable {
    case ok
    case reserved
    case conflict(ShortcutAction)
    case notCustomizable
}

@MainActor
final class ShortcutStore: ObservableObject {
    static let shared = ShortcutStore()

    private static let storageKey = "lumina.shortcuts.overrides"

    /// action rawValue → chord
    @Published private(set) var overrides: [String: ShortcutChord] = [:]
    /// When true, the settings recorder owns keyDown events.
    @Published var isRecordingBinding = false

    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        load()
    }

    func chord(for action: ShortcutAction) -> ShortcutChord {
        if let stored = overrides[action.rawValue] {
            return stored
        }
        return ShortcutCatalog.defaultChord(for: action)
    }

    func display(for action: ShortcutAction) -> String {
        chord(for: action).display
    }

    func isOverridden(_ action: ShortcutAction) -> Bool {
        overrides[action.rawValue] != nil
    }

    func action(matching event: NSEvent, in scope: ShortcutMatchScope) -> ShortcutAction? {
        let candidates: [ShortcutAction]
        switch scope {
        case .global:
            candidates = ShortcutCatalog.customizableActions.filter(\.isGlobal)
        case .reader:
            candidates = ShortcutCatalog.customizableActions.filter { !$0.isGlobal }
        case .allCustomizable:
            candidates = ShortcutCatalog.customizableActions
        }
        for action in candidates {
            if chord(for: action).matches(event) {
                return action
            }
        }
        return nil
    }

    func conflictingAction(with candidate: ShortcutChord, excluding: ShortcutAction?) -> ShortcutAction? {
        for action in ShortcutCatalog.customizableActions {
            if action == excluding { continue }
            if ShortcutCatalog.chordsConflict(chord(for: action), candidate) {
                return action
            }
        }
        return nil
    }

    @discardableResult
    func setChord(_ candidate: ShortcutChord, for action: ShortcutAction) -> ShortcutBindResult {
        guard action.isCustomizable else { return .notCustomizable }
        if ShortcutCatalog.isReserved(candidate) { return .reserved }
        if let other = conflictingAction(with: candidate, excluding: action) {
            return .conflict(other)
        }
        if candidate == ShortcutCatalog.defaultChord(for: action) {
            overrides.removeValue(forKey: action.rawValue)
        } else {
            overrides[action.rawValue] = candidate
        }
        persist()
        objectWillChange.send()
        return .ok
    }

    func reset(_ action: ShortcutAction) {
        guard action.isCustomizable else { return }
        overrides.removeValue(forKey: action.rawValue)
        persist()
        objectWillChange.send()
    }

    func resetAll() {
        overrides.removeAll()
        persist()
        objectWillChange.send()
    }

    private func load() {
        guard let data = defaults.data(forKey: Self.storageKey),
              let decoded = try? JSONDecoder().decode([String: ShortcutChord].self, from: data)
        else {
            overrides = [:]
            return
        }
        overrides = decoded.filter { ShortcutAction(rawValue: $0.key)?.isCustomizable == true }
    }

    private func persist() {
        guard let data = try? JSONEncoder().encode(overrides) else { return }
        defaults.set(data, forKey: Self.storageKey)
    }
}

enum ShortcutMatchScope {
    case global
    case reader
    case allCustomizable
}

/// App-wide monitor for global + reader shortcuts that use modifier chords.
@MainActor
enum ShortcutKeyMonitor {
    private static var monitor: Any?
    /// True while a ReaderView is on screen and should receive reader actions.
    static var isReaderActive = false

    static func install() {
        guard monitor == nil else { return }
        monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            handle(event)
        }
    }

    private static func handle(_ event: NSEvent) -> NSEvent? {
        if ShortcutStore.shared.isRecordingBinding { return event }
        if event.isARepeat { return event }

        let mods = ShortcutModifiers.from(event.modifierFlags)
        let hasChordMods = !mods.intersection([.command, .option, .control]).isEmpty

        if !hasChordMods {
            // Bare keys: skip when typing in an editable field.
            guard isReaderActive, !isTextInputResponder(event.window?.firstResponder) else {
                return event
            }
            guard let action = ShortcutStore.shared.action(matching: event, in: .reader) else {
                return event
            }
            switch action {
            case .prevSegment, .nextSegment:
                // Default ←/→ stay with ScrollViewKeyNSView (segment-list ↑↓ reuse).
                let current = ShortcutStore.shared.chord(for: action)
                let defaultChord = ShortcutCatalog.defaultChord(for: action)
                if ShortcutCatalog.chordsConflict(defaultChord, current) {
                    return event
                }
                postReader(action)
                return nil
            case .scrollUp, .scrollDown, .pageUp, .pageDown, .dismissOverlay:
                return event
            default:
                postReader(action)
                return nil
            }
        }

        if let global = ShortcutStore.shared.action(matching: event, in: .global) {
            switch global {
            case .globalSearch:
                NotificationCenter.default.post(name: .luminaOpenSearch, object: nil)
            case .importBooks:
                NotificationCenter.default.post(name: .luminaImportBook, object: nil)
            default:
                break
            }
            return nil
        }

        if isReaderActive,
           let reader = ShortcutStore.shared.action(matching: event, in: .reader) {
            postReader(reader)
            return nil
        }
        return event
    }

    private static func isTextInputResponder(_ responder: NSResponder?) -> Bool {
        var current = responder
        while let node = current {
            if let textView = node as? NSTextView {
                // Reading body is selectable but not a typing field; bare shortcuts
                // must still work after clicking the feed.
                if textView is LuminaSelectableTextView { return false }
                return textView.isEditable
            }
            if let field = node as? NSTextField {
                return field.isEditable
            }
            current = node.nextResponder
        }
        return false
    }

    private static func postReader(_ action: ShortcutAction) {
        NotificationCenter.default.post(
            name: .luminaReaderShortcutAction,
            object: nil,
            userInfo: [ShortcutActionUserInfo.key: action.rawValue]
        )
    }
}

enum ShortcutActionUserInfo {
    static let key = "action"

    static func action(from note: Notification) -> ShortcutAction? {
        guard let raw = note.userInfo?[key] as? String else { return nil }
        return ShortcutAction(rawValue: raw)
    }
}

extension Notification.Name {
    static let luminaReaderShortcutAction = Notification.Name("lumina.reader.shortcutAction")
}
