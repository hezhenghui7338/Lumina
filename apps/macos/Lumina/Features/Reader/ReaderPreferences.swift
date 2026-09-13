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

    /// Persisted reading position. Segment index is the only resume target;
    /// pixel offsets are deliberately absent.
    struct CachedProgress: Codable, Equatable {
        var index: Int
        var segmentCount: Int

        init(index: Int, segmentCount: Int) {
            self.index = index
            self.segmentCount = segmentCount
        }

        enum CodingKeys: String, CodingKey {
            case index, segmentCount
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

    static func setCachedProgress(index: Int, segmentCount: Int, for bookId: String) {
        let cached = CachedProgress(index: max(index, 0), segmentCount: max(segmentCount, 0))
        guard let data = try? JSONEncoder().encode(cached) else { return }
        defaults.set(data, forKey: progressKey(for: bookId))
    }

    static func clearCachedProgress(for bookId: String) {
        defaults.removeObject(forKey: progressKey(for: bookId))
    }
}

struct ReadingPosition: Equatable {
    var index: Int
    var total: Int

    var percent: Double {
        ReadingProgress.percent(index: index, count: total)
    }
}

/// The single source of truth for reading progress.
///
/// The reader records the segment pinned to the top of the viewport; everything
/// else (library rows, sidebar) reads back from here. Local storage wins over
/// the server, which is only a backup. All state is keyed by book id so
/// switching books can never mix two books' positions.
@MainActor
final class ReadingProgressStore: ObservableObject {
    static let shared = ReadingProgressStore()

    /// Bumped on every debounced position commit so observers can re-read without scroll churn.
    @Published private(set) var positions: [String: ReadingPosition] = [:]

    /// Immediate in-memory cache for fast lookups without triggering SwiftUI objectWillChange storm.
    private var memoryPositions: [String: ReadingPosition] = [:]

    private weak var core: CoreClient?
    /// Recorded but not yet accepted by the sidecar.
    private var pending: [String: Int] = [:]
    /// Last index the sidecar acknowledged, to skip redundant PATCHes.
    private var synced: [String: Int] = [:]
    private var saveTasks: [String: Task<Void, Never>] = [:]
    private var debouncePersistTasks: [String: Task<Void, Never>] = [:]

    private static let patchDebounceNanoseconds: UInt64 = 300_000_000
    private static let localDebounceNanoseconds: UInt64 = 250_000_000

    func attach(core: CoreClient) {
        self.core = core
    }

    /// In-memory position, falling back to disk. Never mutates published state.
    func position(for bookId: String) -> ReadingPosition? {
        if let memory = memoryPositions[bookId] { return memory }
        if let position = positions[bookId] { return position }
        guard let cached = ReaderPreferences.cachedProgress(for: bookId) else { return nil }
        return ReadingPosition(index: cached.index, total: cached.segmentCount)
    }

    /// Resume target for a book, preferring the local record unless the book
    /// was resegmented since it was written.
    func resumeIndex(bookId: String, serverIndex: Int, segmentCount: Int) -> Int {
        let local = position(for: bookId)
        return ReadingProgress.restoreIndex(
            serverIndex: serverIndex,
            localIndex: local?.index,
            localSegmentCount: local?.total,
            currentSegmentCount: segmentCount
        )
    }

    /// Record the segment currently being read. In-memory update is immediate;
    /// local disk write and published notifications are debounced to prevent
    /// layout cascade storms during fast scrolling.
    func record(bookId: String, index: Int, total: Int, immediate: Bool = false) {
        guard !bookId.isEmpty, total > 0 else { return }
        let idx = min(max(index, 0), total - 1)
        let next = ReadingPosition(index: idx, total: total)
        guard memoryPositions[bookId] != next || positions[bookId] != next else { return }
        memoryPositions[bookId] = next

        if immediate {
            debouncePersistTasks[bookId]?.cancel()
            debouncePersistTasks.removeValue(forKey: bookId)
            commitLocalProgress(next, for: bookId)
            scheduleRemoteSave(index: idx, bookId: bookId)
            return
        }

        debouncePersistTasks[bookId]?.cancel()
        debouncePersistTasks[bookId] = Task { [weak self] in
            try? await Task.sleep(nanoseconds: Self.localDebounceNanoseconds)
            guard !Task.isCancelled, let self else { return }
            self.commitLocalProgress(next, for: bookId)
            self.scheduleRemoteSave(index: idx, bookId: bookId)
        }
    }

    private func commitLocalProgress(_ next: ReadingPosition, for bookId: String) {
        ReaderPreferences.setCachedProgress(index: next.index, segmentCount: next.total, for: bookId)
        if positions[bookId] != next {
            positions[bookId] = next
        }
    }

    private func scheduleRemoteSave(index: Int, bookId: String) {
        guard synced[bookId] != index else {
            pending.removeValue(forKey: bookId)
            return
        }
        pending[bookId] = index
        saveTasks[bookId]?.cancel()
        saveTasks[bookId] = Task { [weak self] in
            try? await Task.sleep(nanoseconds: Self.patchDebounceNanoseconds)
            guard !Task.isCancelled else { return }
            await self?.flush(bookId: bookId)
        }
    }

    /// Adopt a server-provided position without scheduling a write back.
    func hydrate(bookId: String, index: Int, total: Int) {
        guard !bookId.isEmpty, total > 0 else { return }
        let idx = min(max(index, 0), total - 1)
        let next = ReadingPosition(index: idx, total: total)
        memoryPositions[bookId] = next
        guard positions[bookId] != next else { return }
        positions[bookId] = next
        synced[bookId] = idx
    }

    func flush(bookId: String, timeoutNanoseconds: UInt64 = 2_000_000_000) async {
        debouncePersistTasks[bookId]?.cancel()
        debouncePersistTasks.removeValue(forKey: bookId)
        if let memory = memoryPositions[bookId] {
            commitLocalProgress(memory, for: bookId)
        }
        saveTasks[bookId]?.cancel()
        saveTasks.removeValue(forKey: bookId)
        guard let index = pending[bookId], let core else { return }
        pending.removeValue(forKey: bookId)

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
            synced[bookId] = index
        } catch {
            timeout.cancel()
            // Keep it pending unless a newer position already replaced it.
            if pending[bookId] == nil {
                pending[bookId] = index
            }
        }
    }

    func flushAll() async {
        for bookId in Array(memoryPositions.keys) {
            if let memory = memoryPositions[bookId] {
                commitLocalProgress(memory, for: bookId)
            }
        }
        for bookId in pending.keys {
            await flush(bookId: bookId)
        }
    }

    func forget(bookId: String) {
        debouncePersistTasks[bookId]?.cancel()
        debouncePersistTasks.removeValue(forKey: bookId)
        saveTasks[bookId]?.cancel()
        saveTasks.removeValue(forKey: bookId)
        pending.removeValue(forKey: bookId)
        synced.removeValue(forKey: bookId)
        memoryPositions.removeValue(forKey: bookId)
        positions.removeValue(forKey: bookId)
        ReaderPreferences.clearCachedProgress(for: bookId)
    }
}
