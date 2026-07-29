import Foundation

struct IngestProgress: Equatable {
    var page: Int
    var total: Int
    var message: String

    var label: String {
        guard total > 0 else { return message.isEmpty ? "处理中" : message }
        return "处理中 · OCR \(page)/\(total)"
    }
}

@MainActor
final class LibraryViewModel: ObservableObject {
    @Published var books: [BookSummary] = []
    @Published var collection: LibraryCollection = .all
    @Published var sort: LibrarySort = .recent
    @Published var classifyingIds: Set<String> = []
    @Published var ingestProgress: [String: IngestProgress] = [:]

    private var ingestEventTasks: [String: Task<Void, Never>] = [:]

    func loadPreferences() {
        if let raw = UserDefaults.standard.string(forKey: Self.collectionKey),
           let value = LibraryCollection(rawValue: raw) {
            collection = value
        }
        if let raw = UserDefaults.standard.string(forKey: Self.sortKey),
           let value = LibrarySort(rawValue: raw) {
            sort = value
        }
    }

    func persistPreferences() {
        UserDefaults.standard.set(collection.rawValue, forKey: Self.collectionKey)
        UserDefaults.standard.set(sort.rawValue, forKey: Self.sortKey)
    }

    func prepareForNewImport() {
        collection = .all
        persistPreferences()
    }

    func refresh(using core: CoreClient, preserveOrder: Bool = false) async throws {
        let fetched = try await core.listBooks(collection: collection, sort: sort)
        books = preserveOrder && !books.isEmpty
            ? Self.mergePreservingOrder(existing: books, fetched: fetched)
            : fetched
        syncIngestSubscriptions(using: core)
    }

    func syncIngestSubscriptions(using core: CoreClient) {
        let processingIds = Set(books.filter(\.isProcessing).map(\.id))
        for (bookId, task) in ingestEventTasks where !processingIds.contains(bookId) {
            task.cancel()
            ingestEventTasks.removeValue(forKey: bookId)
            ingestProgress.removeValue(forKey: bookId)
        }
        for bookId in processingIds where ingestEventTasks[bookId] == nil {
            ingestEventTasks[bookId] = core.subscribeEvents(bookId: bookId) { [weak self] event in
                Task { @MainActor in
                    self?.handleIngestEvent(bookId: bookId, event: event, core: core)
                }
            }
        }
    }

    private func handleIngestEvent(bookId: String, event: [String: Any], core: CoreClient) {
        let type = event["type"] as? String
        switch type {
        case "ingest_progress":
            let page = event["page"] as? Int ?? 0
            let total = event["total"] as? Int ?? 0
            let message = event["message"] as? String ?? ""
            ingestProgress[bookId] = IngestProgress(page: page, total: total, message: message)
        case "ingest_complete":
            ingestProgress.removeValue(forKey: bookId)
            ingestEventTasks[bookId]?.cancel()
            ingestEventTasks.removeValue(forKey: bookId)
            Task {
                try? await refresh(using: core, preserveOrder: true)
                NotificationCenter.default.post(name: .luminaLibraryRefresh, object: nil)
            }
        case "ingest_failed":
            ingestProgress.removeValue(forKey: bookId)
            ingestEventTasks[bookId]?.cancel()
            ingestEventTasks.removeValue(forKey: bookId)
            Task { try? await refresh(using: core, preserveOrder: true) }
        default:
            break
        }
    }

    static func mergePreservingOrder(existing: [BookSummary], fetched: [BookSummary]) -> [BookSummary] {
        let byId = Dictionary(uniqueKeysWithValues: fetched.map { ($0.id, $0) })
        var merged = existing.compactMap { byId[$0.id] }
        let known = Set(existing.map(\.id))
        merged.append(contentsOf: fetched.filter { !known.contains($0.id) })
        return merged
    }

    func setCollection(_ value: LibraryCollection, using core: CoreClient) async throws {
        collection = value
        persistPreferences()
        try await refresh(using: core)
    }

    func setSort(_ value: LibrarySort, using core: CoreClient) async throws {
        sort = value
        persistPreferences()
        try await refresh(using: core)
    }

    func toggleFavorite(_ book: BookSummary, using core: CoreClient) async throws {
        let updated = try await core.updateBook(id: book.id, isFavorite: !book.isFavorite)
        replace(updated)
    }

    func deleteBook(id: String, using core: CoreClient) async throws {
        ingestEventTasks[id]?.cancel()
        ingestEventTasks.removeValue(forKey: id)
        ingestProgress.removeValue(forKey: id)
        try await core.deleteBook(id: id)
        books.removeAll { $0.id == id }
    }

    func deleteBooks(ids: [String], using core: CoreClient) async throws {
        guard !ids.isEmpty else { return }
        for id in ids {
            ingestEventTasks[id]?.cancel()
            ingestEventTasks.removeValue(forKey: id)
            ingestProgress.removeValue(forKey: id)
        }
        try await core.deleteBooks(ids: ids)
        books.removeAll { ids.contains($0.id) }
    }

    func setFavorite(ids: [String], isFavorite: Bool, using core: CoreClient) async throws {
        guard !ids.isEmpty else { return }
        let updated = try await core.setBooksFavorite(ids: ids, isFavorite: isFavorite)
        for book in updated {
            replace(book)
        }
    }

    func reclassify(id: String, using core: CoreClient) async throws {
        classifyingIds.insert(id)
        defer { classifyingIds.remove(id) }
        try await core.classifyBook(id: id)
        try await Task.sleep(nanoseconds: 800_000_000)
        try await refresh(using: core, preserveOrder: true)
    }

    func replace(_ book: BookSummary) {
        guard let index = books.firstIndex(where: { $0.id == book.id }) else { return }
        books[index] = book
    }

    var hasIncompleteSummaries: Bool {
        books.contains { $0.summaryTotal > 0 && $0.summaryReady < $0.summaryTotal }
    }

    var hasProcessingBooks: Bool {
        books.contains(where: \.isProcessing)
    }

    private static let collectionKey = "lumina.library.collection"
    private static let sortKey = "lumina.library.sort"
}
