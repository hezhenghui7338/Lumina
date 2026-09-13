import Foundation

struct IngestProgress: Equatable {
    var page: Int
    var total: Int
    var message: String

    var label: String {
        if total > 0 {
            let pct = min(100, max(0, Int((Double(page) / Double(max(total, 1)) * 100.0).rounded())))
            if !message.isEmpty { return "\(message) · \(pct)%" }
            return "分段中 · \(pct)%"
        }
        if !message.isEmpty { return message }
        return "分段中"
    }
}

enum BookshelfViewMode: String, CaseIterable, Identifiable {
    case grid, list

    var id: String { rawValue }

    var label: String {
        switch self {
        case .grid: return "网格"
        case .list: return "列表"
        }
    }

    var systemImage: String {
        switch self {
        case .grid: return "square.grid.2x2"
        case .list: return "list.bullet"
        }
    }
}

enum BookDisplayTitle {
    static func normalized(_ raw: String) -> String? {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }
}

enum BookshelfPaging {
    static let defaultPageSize = 10
    static let allowedPageSizes = [10, 20, 50, 100]

    static func normalizedPageSize(_ value: Int) -> Int {
        allowedPageSizes.contains(value) ? value : defaultPageSize
    }

    static func pageCount(total: Int, pageSize: Int) -> Int {
        guard pageSize > 0, total > 0 else { return 0 }
        return (total + pageSize - 1) / pageSize
    }

    static func clampedPageIndex(_ index: Int, pageCount: Int) -> Int {
        guard pageCount > 0 else { return 0 }
        return min(max(0, index), pageCount - 1)
    }

    static func slice<T>(_ items: [T], pageIndex: Int, pageSize: Int) -> [T] {
        guard pageSize > 0, !items.isEmpty else { return [] }
        let count = pageCount(total: items.count, pageSize: pageSize)
        let page = clampedPageIndex(pageIndex, pageCount: count)
        let start = page * pageSize
        guard start < items.count else { return [] }
        let end = min(start + pageSize, items.count)
        return Array(items[start..<end])
    }
}

enum BookshelfPageTurnKeyPolicy {
    static let leftArrowKeyCode: UInt16 = 123
    static let rightArrowKeyCode: UInt16 = 124

    /// Returns -1 for previous page, +1 for next page, or nil if not a bookshelf page-turn key event.
    static func delta(
        keyCode: UInt16,
        characters: String? = nil,
        hasModifiers: Bool = false,
        isRepeat: Bool = false
    ) -> Int? {
        if isRepeat { return nil }
        if hasModifiers { return nil }

        switch keyCode {
        case leftArrowKeyCode:
            return -1
        case rightArrowKeyCode:
            return 1
        default:
            break
        }

        if let chars = characters, chars.count == 1, let scalar = chars.unicodeScalars.first {
            switch scalar.value {
            case 0xF702: // NSLeftArrowFunctionKey
                return -1
            case 0xF703: // NSRightArrowFunctionKey
                return 1
            default:
                break
            }
        }

        return nil
    }
}

@MainActor
final class LibraryViewModel: ObservableObject {
    @Published var books: [BookSummary] = []
    @Published var query = LibraryFacetQuery()
    @Published var sort: LibrarySort = .recent
    @Published var sortOrder: LibrarySortOrder = .descending
    @Published var viewMode: BookshelfViewMode = .grid
    @Published var titleQuery: String = ""
    @Published var categories: [String] = LibraryFilter.fallbackCategories
    @Published var classifyingIds: Set<String> = []
    @Published var ingestProgress: [String: IngestProgress] = [:]
    @Published var summarizeOverview: SummarizeOverview?
    /// Zero-based page into `matchedBooks`. Reset when facets / title / sort / page size change.
    @Published var pageIndex: Int = 0
    /// Allowed values: 10 / 20 / 50 / 100. Persisted; tests may override.
    @Published var pageSize: Int = BookshelfPaging.defaultPageSize

    private var ingestEventTasks: [String: Task<Void, Never>] = [:]

    var sidebarCollections: [LibraryCollection] {
        LibraryCollection.sidebarItems(categories: categories, selectedCategory: query.category)
    }

    /// Filtered + sorted shelf (full match set; used for counts and paging).
    var matchedBooks: [BookSummary] {
        var result = books.filter { query.matches($0) }
        let trimmedTitle = titleQuery.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmedTitle.isEmpty {
            result = result.filter { $0.title.localizedCaseInsensitiveContains(trimmedTitle) }
        }
        result = Self.sorted(result, by: sort, order: sortOrder)
        if query.isDefault, sort == .recent {
            result = Self.prioritizeSummarizeActivity(result)
        }
        return result
    }

    var pageCount: Int {
        BookshelfPaging.pageCount(total: matchedBooks.count, pageSize: pageSize)
    }

    var showsPagination: Bool { !matchedBooks.isEmpty }

    /// Current page slice — what the grid/list should bind.
    var pagedBooks: [BookSummary] {
        BookshelfPaging.slice(matchedBooks, pageIndex: pageIndex, pageSize: pageSize)
    }

    /// Alias for the visible page (keeps older call sites / small-fixture tests working).
    var displayedBooks: [BookSummary] { pagedBooks }

    func count(for item: LibraryCollection) -> Int {
        let projected = query.projecting(item)
        return books.filter { projected.matches($0) }.count
    }

    func loadPreferences() {
        if let data = UserDefaults.standard.data(forKey: Self.facetsKey),
           let stored = try? JSONDecoder().decode(LibraryFacetQuery.self, from: data) {
            query = stored
        } else if let text = UserDefaults.standard.string(forKey: Self.facetsKey),
                  let data = text.data(using: .utf8),
                  let stored = try? JSONDecoder().decode(LibraryFacetQuery.self, from: data) {
            query = stored
        } else if let raw = UserDefaults.standard.string(forKey: Self.filterKey) {
            query = LibraryFacetQuery.fromLegacyCollection(raw)
        } else if let legacy = UserDefaults.standard.string(forKey: Self.legacyCollectionKey) {
            query = LibraryFacetQuery.fromLegacyCollection(legacy)
        }
        if let raw = UserDefaults.standard.string(forKey: Self.sortKey),
           let value = LibrarySort(rawValue: raw) {
            sort = value
        }
        if let raw = UserDefaults.standard.string(forKey: Self.sortOrderKey),
           let value = LibrarySortOrder(rawValue: raw) {
            sortOrder = value
        } else {
            sortOrder = sort.defaultOrder
        }
        if let raw = UserDefaults.standard.string(forKey: Self.viewModeKey),
           let value = BookshelfViewMode(rawValue: raw) {
            viewMode = value
        }
        if UserDefaults.standard.object(forKey: Self.pageSizeKey) != nil {
            pageSize = BookshelfPaging.normalizedPageSize(
                UserDefaults.standard.integer(forKey: Self.pageSizeKey)
            )
        } else {
            pageSize = BookshelfPaging.defaultPageSize
        }
    }

    func persistPreferences() {
        if let data = try? JSONEncoder().encode(query) {
            UserDefaults.standard.set(data, forKey: Self.facetsKey)
        }
        UserDefaults.standard.set(sort.rawValue, forKey: Self.sortKey)
        UserDefaults.standard.set(sortOrder.rawValue, forKey: Self.sortOrderKey)
        UserDefaults.standard.set(viewMode.rawValue, forKey: Self.viewModeKey)
        UserDefaults.standard.set(pageSize, forKey: Self.pageSizeKey)
    }

    func loadCategories(using core: CoreClient) async {
        if let fetched = try? await core.listBookCategories(), !fetched.isEmpty {
            categories = fetched
        }
    }

    func refresh(using core: CoreClient, preserveOrder: Bool = false) async throws {
        let fetched = try await core.listBooks(filter: .all, sort: sort)
        summarizeOverview = try? await core.fetchSummarizeOverview()
        books = preserveOrder && !books.isEmpty
            ? Self.mergePreservingOrder(existing: books, fetched: fetched)
            : fetched
        books = Self.overlayLocalProgress(books) { ReadingProgressStore.shared.position(for: $0) }
        clampPageIndexIfNeeded()
        syncIngestSubscriptions(using: core)
    }

    func syncIngestSubscriptions(using core: CoreClient) {
        let processingIds = Set(books.filter(\.isProcessing).map(\.id))
        for book in books where
            book.processing_kind == "resegment" && ingestProgress[book.id] == nil {
            ingestProgress[book.id] = IngestProgress(
                page: 0,
                total: 0,
                message: "正在重新分段…"
            )
        }
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
        case "resegment_started":
            ingestProgress[bookId] = IngestProgress(
                page: 0,
                total: 0,
                message: "正在重新分段…"
            )
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
        case "ingest_failed", "ingest_cancelled", "resegment_failed", "resegment_cancelled":
            ingestProgress.removeValue(forKey: bookId)
            ingestEventTasks[bookId]?.cancel()
            ingestEventTasks.removeValue(forKey: bookId)
            Task {
                try? await refresh(using: core, preserveOrder: true)
                NotificationCenter.default.post(name: .luminaLibraryRefresh, object: nil)
            }
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

    /// The local record is the truth for what the user has read; the server list
    /// only backs it up and can lag behind (the PATCH is coalesced).
    static func overlayLocalProgress(
        _ books: [BookSummary],
        openedAt: Date = Date(),
        cached: (String) -> ReadingPosition?
    ) -> [BookSummary] {
        books.map { book in
            guard let local = cached(book.id) else { return book }
            var copy = book
            copy.current_segment_index = ReadingProgress.restoreIndex(
                serverIndex: book.current_segment_index ?? 0,
                localIndex: local.index,
                localSegmentCount: local.total,
                currentSegmentCount: book.readingTotal
            )
            if local.total == book.readingTotal {
                copy.readingPercent = local.percent
            }
            // A local record means the book has been opened at least once.
            if copy.last_opened_at == nil {
                copy.last_opened_at = ISO8601DateFormatter().string(from: openedAt)
            }
            return copy
        }
    }

    static func prioritizeSummarizeActivity(_ books: [BookSummary]) -> [BookSummary] {
        var running: [BookSummary] = []
        var queued: [BookSummary] = []
        var rest: [BookSummary] = []
        for book in books {
            switch book.summarize_state {
            case "running":
                running.append(book)
            case "queued":
                queued.append(book)
            default:
                rest.append(book)
            }
        }
        return running + queued + rest
    }

    static func sorted(
        _ books: [BookSummary],
        by sort: LibrarySort,
        order: LibrarySortOrder? = nil
    ) -> [BookSummary] {
        let resolved = order ?? sort.defaultOrder
        let base: [BookSummary]
        switch sort {
        case .recent:
            base = books.sorted { lhs, rhs in
                switch (lhs.last_opened_at, rhs.last_opened_at) {
                case (nil, nil):
                    return (lhs.created_at ?? "") > (rhs.created_at ?? "")
                case (nil, _):
                    return false
                case (_, nil):
                    return true
                case let (left?, right?):
                    return left > right
                }
            }
        case .added:
            base = books.sorted { ($0.created_at ?? "") > ($1.created_at ?? "") }
        case .title:
            base = books.sorted {
                $0.title.localizedStandardCompare($1.title) == .orderedAscending
            }
        case .segments:
            base = books.sorted { lhs, rhs in
                let left = lhs.segment_count ?? 0
                let right = rhs.segment_count ?? 0
                if left != right { return left > right }
                return lhs.title.localizedStandardCompare(rhs.title) == .orderedAscending
            }
        case .progress:
            base = books.sorted { lhs, rhs in
                let left = lhs.sortReadingProgress
                let right = rhs.sortReadingProgress
                if left != right { return left > right }
                return lhs.title.localizedStandardCompare(rhs.title) == .orderedAscending
            }
        case .favorite:
            base = books.sorted { lhs, rhs in
                if lhs.isFavorite != rhs.isFavorite { return lhs.isFavorite && !rhs.isFavorite }
                switch (lhs.last_opened_at, rhs.last_opened_at) {
                case (nil, nil):
                    return (lhs.created_at ?? "") > (rhs.created_at ?? "")
                case (nil, _):
                    return false
                case (_, nil):
                    return true
                case let (left?, right?):
                    return left > right
                }
            }
        }
        return resolved == sort.defaultOrder ? base : Array(base.reversed())
    }

    func resetPage() {
        pageIndex = 0
    }

    var canGoPreviousPage: Bool {
        pageCount > 1 && pageIndex > 0
    }

    var canGoNextPage: Bool {
        pageCount > 1 && pageIndex < pageCount - 1
    }

    @discardableResult
    func previousPage() -> Bool {
        guard canGoPreviousPage else { return false }
        setPage(pageIndex - 1)
        return true
    }

    @discardableResult
    func nextPage() -> Bool {
        guard canGoNextPage else { return false }
        setPage(pageIndex + 1)
        return true
    }

    func setPage(_ index: Int) {
        pageIndex = BookshelfPaging.clampedPageIndex(index, pageCount: pageCount)
    }

    func clampPageIndexIfNeeded() {
        let clamped = BookshelfPaging.clampedPageIndex(pageIndex, pageCount: pageCount)
        if clamped != pageIndex {
            pageIndex = clamped
        }
    }

    func selectFacet(_ item: LibraryCollection) {
        var next = query
        next.apply(item)
        query = next
        resetPage()
        persistPreferences()
    }

    func setSort(_ value: LibrarySort) {
        sort = value
        sortOrder = value.defaultOrder
        resetPage()
        persistPreferences()
    }

    func setSortOrder(_ value: LibrarySortOrder) {
        sortOrder = value
        resetPage()
        persistPreferences()
    }

    func setViewMode(_ value: BookshelfViewMode) {
        viewMode = value
        persistPreferences()
    }

    func setPageSize(_ value: Int) {
        let next = BookshelfPaging.normalizedPageSize(value)
        guard next != pageSize else { return }
        pageSize = next
        resetPage()
        persistPreferences()
    }

    func toggleFavorite(_ book: BookSummary, using core: CoreClient) async throws {
        let updated = try await core.updateBook(id: book.id, isFavorite: !book.isFavorite)
        replace(updated)
    }

    func renameBook(_ book: BookSummary, title: String, using core: CoreClient) async throws {
        guard let prepared = BookDisplayTitle.normalized(title) else { return }
        let updated = try await core.updateBook(id: book.id, title: prepared)
        replace(updated)
    }

    func deleteBook(id: String, using core: CoreClient) async throws {
        ingestEventTasks[id]?.cancel()
        ingestEventTasks.removeValue(forKey: id)
        ingestProgress.removeValue(forKey: id)
        try await core.deleteBook(id: id)
        books.removeAll { $0.id == id }
        clampPageIndexIfNeeded()
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
        clampPageIndexIfNeeded()
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

    func resegmentBook(
        _ book: BookSummary,
        chunkTargetChars: Int,
        segmentTier: SegmentTier = .normal,
        using core: CoreClient
    ) async throws {
        ReaderPreferences.clearCachedProgress(for: book.id)
        try await core.resegmentBook(
            bookId: book.id,
            chunkTargetChars: chunkTargetChars,
            segmentTier: segmentTier
        )
        try await refresh(using: core, preserveOrder: true)
    }

    func replace(_ book: BookSummary) {
        guard let index = books.firstIndex(where: { $0.id == book.id }) else { return }
        books[index] = book
    }

    /// Re-apply the store's positions to the rows. Called whenever the reader
    /// records a new position, so the shelf never drifts from what is on screen.
    func applyLocalProgress(_ positions: [String: ReadingPosition], openedAt: Date = Date()) {
        books = Self.overlayLocalProgress(books, openedAt: openedAt) { positions[$0] }
    }

    var hasIncompleteSummaries: Bool {
        books.contains { $0.summaryTotal > 0 && $0.summaryReady < $0.summaryTotal }
    }

    var needsSummarizePolling: Bool {
        if let overview = summarizeOverview, overview.activeCount > 0 {
            return true
        }
        if hasProcessingBooks { return true }
        return books.contains {
            if $0.isSegmenting { return true }
            switch $0.summarize_state {
            case "running", "queued", "paused": return true
            default:
                return $0.summaryTotal > 0 && $0.summaryReady < $0.summaryTotal
            }
        }
    }

    var hasProcessingBooks: Bool {
        books.contains(where: \.isProcessing)
    }

    private static let facetsKey = "lumina.library.facets"
    private static let filterKey = "lumina.library.filter"
    private static let legacyCollectionKey = "lumina.library.collection"
    private static let sortKey = "lumina.library.sort"
    private static let sortOrderKey = "lumina.library.sortOrder"
    private static let viewModeKey = "lumina.library.viewMode"
    private static let pageSizeKey = "lumina.library.pageSize"
}
