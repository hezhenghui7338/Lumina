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
    private static var defaults: UserDefaults { .standard }

    private static func storageKey(for bookId: String) -> String {
        "lumina.reader.contentMode.\(bookId)"
    }

    private static func progressKey(for bookId: String) -> String {
        "lumina.reader.progress.\(bookId)"
    }

    struct CachedProgress: Codable, Equatable {
        var index: Int
        var segmentCount: Int
        var offsetY: Double
        var contentMode: String?

        init(index: Int, segmentCount: Int, offsetY: Double = 0, contentMode: String? = nil) {
            self.index = index
            self.segmentCount = segmentCount
            self.offsetY = offsetY
            self.contentMode = contentMode
        }

        enum CodingKeys: String, CodingKey {
            case index, segmentCount, offsetY, contentMode
        }

        init(from decoder: Decoder) throws {
            let container = try decoder.container(keyedBy: CodingKeys.self)
            index = try container.decode(Int.self, forKey: .index)
            segmentCount = try container.decode(Int.self, forKey: .segmentCount)
            offsetY = try container.decodeIfPresent(Double.self, forKey: .offsetY) ?? 0
            contentMode = try container.decodeIfPresent(String.self, forKey: .contentMode)
        }
    }

    static func contentMode(for bookId: String) -> ReaderContentMode {
        guard let raw = defaults.string(forKey: storageKey(for: bookId)),
              let mode = ReaderContentMode(rawValue: raw)
        else {
            return .summary
        }
        return mode
    }

    static func setContentMode(_ mode: ReaderContentMode, for bookId: String) {
        defaults.set(mode.rawValue, forKey: storageKey(for: bookId))
    }

    static func cachedProgress(for bookId: String) -> CachedProgress? {
        guard let data = defaults.data(forKey: progressKey(for: bookId)) else { return nil }
        return try? JSONDecoder().decode(CachedProgress.self, from: data)
    }

    static func setCachedProgress(
        index: Int,
        segmentCount: Int,
        offsetY: Double = 0,
        contentMode: String? = nil,
        for bookId: String
    ) {
        let cached = CachedProgress(
            index: index,
            segmentCount: segmentCount,
            offsetY: max(0, offsetY),
            contentMode: contentMode
        )
        guard let data = try? JSONEncoder().encode(cached) else { return }
        defaults.set(data, forKey: progressKey(for: bookId))
    }

    static func clearCachedProgress(for bookId: String) {
        defaults.removeObject(forKey: progressKey(for: bookId))
    }
}

/// Immediate local persist + library display; coalesced PATCH to sidecar.
@MainActor
final class ReadingProgressStore {
    static let shared = ReadingProgressStore()

    private weak var core: CoreClient?
    private var pendingBookId: String?
    private var pendingIndex: Int?
    private var pendingOffsetY: Double = 0
    private var lastFlushed: (bookId: String, index: Int)?
    private var saveTask: Task<Void, Never>?

    func attach(core: CoreClient) {
        self.core = core
    }

    func noteVisibleSegment(
        bookId: String,
        index: Int,
        offsetY: CGFloat = 0,
        segmentCount: Int,
        contentMode: ReaderContentMode? = nil,
        confirmedHit: Bool = false
    ) {
        guard !bookId.isEmpty else { return }
        let last = segmentCount > 0 ? segmentCount - 1 : nil
        let idx = ReadingProgress.saveIndex(visibleIndex: index, lastIndex: last)
        let cached = ReaderPreferences.cachedProgress(for: bookId)
        guard ReadingProgress.shouldReplaceCachedIndex(
            cachedIndex: cached?.index,
            cachedSegmentCount: cached?.segmentCount,
            nextIndex: idx,
            nextSegmentCount: max(segmentCount, 0),
            confirmedHit: confirmedHit
        ) else { return }
        let roundedOffset = (Double(max(0, offsetY)) * 10).rounded() / 10
        ReaderPreferences.setCachedProgress(
            index: idx,
            segmentCount: max(segmentCount, 0),
            offsetY: roundedOffset,
            contentMode: contentMode?.rawValue,
            for: bookId
        )
        let indexUnchanged = pendingBookId == bookId && pendingIndex == idx
        let offsetUnchanged = abs(pendingOffsetY - roundedOffset) < 1
        pendingBookId = bookId
        pendingIndex = idx
        pendingOffsetY = roundedOffset
        if !indexUnchanged {
            NotificationCenter.default.post(
                name: .luminaReadingProgressDidChange,
                object: nil,
                userInfo: ["bookId": bookId, "segmentIndex": idx]
            )
        }
        if indexUnchanged, offsetUnchanged,
           lastFlushed?.bookId == bookId, lastFlushed?.index == idx {
            return
        }
        if indexUnchanged, lastFlushed?.bookId == bookId, lastFlushed?.index == idx {
            return
        }
        saveTask?.cancel()
        saveTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 150_000_000)
            guard !Task.isCancelled else { return }
            await self?.flush()
        }
    }

    func flush(timeoutNanoseconds: UInt64 = 2_000_000_000) async {
        saveTask?.cancel()
        saveTask = nil
        guard let bookId = pendingBookId, let index = pendingIndex, let core else {
            return
        }
        if lastFlushed?.bookId == bookId, lastFlushed?.index == index {
            pendingBookId = nil
            pendingIndex = nil
            return
        }
        pendingBookId = nil
        pendingIndex = nil

        let save = Task {
            try await core.saveReadingProgress(bookId: bookId, segmentIndex: index)
        }
        let timeout = Task {
            try await Task.sleep(nanoseconds: timeoutNanoseconds)
            save.cancel()
        }
        do {
            try await save.value
            timeout.cancel()
            lastFlushed = (bookId, index)
        } catch {
            timeout.cancel()
            pendingBookId = bookId
            pendingIndex = index
        }
    }
}
