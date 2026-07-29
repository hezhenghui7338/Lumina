import Foundation

enum ReaderContentMode: String, CaseIterable {
    case summary
    case original

    var label: String {
        switch self {
        case .summary: "摘要"
        case .original: "原文"
        }
    }
}

enum ReaderPreferences {
    private static func storageKey(for bookId: String) -> String {
        "lumina.reader.contentMode.\(bookId)"
    }

    static func contentMode(for bookId: String) -> ReaderContentMode {
        guard let raw = UserDefaults.standard.string(forKey: storageKey(for: bookId)),
              let mode = ReaderContentMode(rawValue: raw)
        else {
            return .summary
        }
        return mode
    }

    static func setContentMode(_ mode: ReaderContentMode, for bookId: String) {
        UserDefaults.standard.set(mode.rawValue, forKey: storageKey(for: bookId))
    }
}
