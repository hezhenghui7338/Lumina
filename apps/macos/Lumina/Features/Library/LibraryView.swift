import SwiftUI
import AppKit

struct LibraryView: View {
    @EnvironmentObject private var core: CoreClient
    @EnvironmentObject private var sidecar: SidecarManager
    @Binding var selectedBookId: String?
    @StateObject private var viewModel = LibraryViewModel()
    @State private var bookPendingDelete: BookSummary?
    @State private var actionError: String?
    @State private var isSelectionMode = false
    @State private var checkedBookIds: Set<String> = []
    @State private var batchDeleteCount: Int?
    @State private var bookPendingExport: BookSummary?
    @State private var exportIncludeNotes = false
    @State private var exportDocument = MarkdownExportDocument(text: "")
    @State private var showFileExporter = false
    @State private var exportDefaultFilename = "summary.md"
    @State private var exportFallbackBookTitle = ""
    @State private var shouldPresentFileExporter = false
    @State private var exportFeedback: ExportFeedback?
    @State private var summarizeActionInFlight = false

    var onImport: () -> Void
    var onSearch: () -> Void
    var onShowAllNotes: () -> Void
    var onStartSummarize: () -> Void
    var onStopSummarize: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            libraryControls
            if isSelectionMode {
                selectionToolbar
                Divider()
            }
            bookList
        }
        .navigationTitle("书库")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button(action: onImport) {
                    Label("导入", systemImage: "square.and.arrow.down")
                }
                .foregroundStyle(LuminaTheme.accent)
            }
            ToolbarItemGroup(placement: .automatic) {
                if let overview = viewModel.summarizeOverview, overview.activeCount > 0 {
                    Text("\(overview.counts.running) 进行中 · \(overview.counts.queued) 排队")
                        .font(.caption2)
                        .foregroundStyle(LuminaTheme.textSecondary)

                    Button {
                        Task { await stopAllSummarize() }
                    } label: {
                        if summarizeActionInFlight {
                            ProgressView()
                                .controlSize(.small)
                        } else {
                            Label("停止全部摘要", systemImage: "stop.fill")
                        }
                    }
                    .disabled(summarizeActionInFlight)
                    .help("停止所有正在摘要和排队中的任务")
                }

                if !viewModel.books.isEmpty {
                    Button {
                        toggleSelectionMode()
                    } label: {
                        Image(systemName: isSelectionMode ? "checklist.checked" : "checklist")
                    }
                    .help(isSelectionMode ? "退出多选" : "多选")
                }

                Button(action: onSearch) {
                    Label("搜索", systemImage: "magnifyingglass")
                }
                .keyboardShortcut("k", modifiers: .command)

                Button(action: onShowAllNotes) {
                    Label("全部笔记", systemImage: "note.text")
                }

                Menu {
                    Button(selectedBookId == nil ? "开始全部摘要" : "开始摘要") {
                        onStartSummarize()
                    }
                    Button(selectedBookId == nil ? "停止全部摘要" : "停止摘要") {
                        onStopSummarize()
                    }
                } label: {
                    Label("摘要", systemImage: "text.alignleft")
                }

                if let book = selectedBook, book.summaryReady > 0 {
                    Button {
                        presentExport(for: book)
                    } label: {
                        Label("导出", systemImage: "square.and.arrow.up")
                    }
                }
            }
        }
        .onAppear { viewModel.loadPreferences() }
        .task(id: sidecar.isRunning) {
            guard sidecar.isRunning else { return }
            await viewModel.loadCategories(using: core)
            await refreshBooks()
        }
        .task(id: viewModel.needsSummarizePolling) {
            await pollSummaryProgress()
        }
        .onReceive(NotificationCenter.default.publisher(for: .luminaLibraryRefresh)) { _ in
            Task { await refreshBooks() }
        }
        .onChange(of: selectedBookId) { oldId, newId in
            if oldId != nil, newId == nil {
                Task { await refreshBooks() }
            }
        }
        .confirmationDialog(
            "确定删除这本书？",
            isPresented: Binding(
                get: { bookPendingDelete != nil },
                set: { if !$0 { bookPendingDelete = nil } }
            ),
            titleVisibility: .visible
        ) {
            if let book = bookPendingDelete {
                Button("删除《\(book.title)》", role: .destructive) {
                    Task { await confirmDelete(book) }
                }
            }
            Button("取消", role: .cancel) {
                bookPendingDelete = nil
            }
        } message: {
            Text("将删除本地副本、摘要与笔记，且不可恢复。")
        }
        .confirmationDialog(
            batchDeleteTitle,
            isPresented: Binding(
                get: { batchDeleteCount != nil },
                set: { if !$0 { batchDeleteCount = nil } }
            ),
            titleVisibility: .visible
        ) {
            if let count = batchDeleteCount {
                Button("删除 \(count) 本书", role: .destructive) {
                    let ids = Array(checkedBookIds)
                    batchDeleteCount = nil
                    Task { await confirmBatchDelete(ids) }
                }
            }
            Button("取消", role: .cancel) {
                batchDeleteCount = nil
            }
        } message: {
            Text("将删除本地副本、摘要与笔记，且不可恢复。")
        }
        .alert("出错了", isPresented: actionErrorPresented) {
            Button("好") { actionError = nil }
        } message: {
            Text(actionError ?? "")
        }
        .exportFeedbackAlert($exportFeedback)
        .sheet(item: $bookPendingExport, onDismiss: presentFileExporterIfNeeded) { book in
            ExportSheet(
                isPresented: Binding(
                    get: { bookPendingExport != nil },
                    set: { if !$0 { bookPendingExport = nil } }
                ),
                includeNotes: $exportIncludeNotes,
                summaryReadyCount: book.summaryReady,
                summaryTotalCount: book.summaryTotal,
                onFetchMarkdown: {
                    try await BookMarkdownExporter.fetchMarkdown(
                        core: core,
                        bookId: book.id,
                        summaryReadyCount: book.summaryReady,
                        includeNotes: exportIncludeNotes
                    )
                },
                onMarkdownReady: { markdown in
                    exportDocument = MarkdownExportDocument(text: markdown)
                    exportDefaultFilename = BookMarkdownExporter.defaultFilename(for: book.title)
                    exportFallbackBookTitle = book.title
                    shouldPresentFileExporter = true
                    bookPendingExport = nil
                },
                onError: { actionError = $0 }
            )
        }
        .fileExporter(
            isPresented: $showFileExporter,
            document: exportDocument,
            contentType: .plainText,
            defaultFilename: exportDefaultFilename
        ) { result in
            handleFileExportCompletion(result)
        }
    }

    private func presentFileExporterIfNeeded() {
        guard shouldPresentFileExporter else { return }
        shouldPresentFileExporter = false
        showFileExporter = true
    }

    @MainActor
    private func handleFileExportCompletion(_ result: Result<URL, Error>) {
        let markdown = exportDocument.text
        let bookTitle = exportFallbackBookTitle
        exportDocument = MarkdownExportDocument(text: "")
        exportFallbackBookTitle = ""

        switch result {
        case .success:
            exportFeedback = BookMarkdownExporter.feedback(from: result)
        case .failure(let error) where BookMarkdownExporter.isUserCancellation(error):
            exportFeedback = .cancelled
        case .failure:
            exportFeedback = BookMarkdownExporter.presentSavePanelFallback(
                markdown: markdown,
                bookTitle: bookTitle
            )
        }
    }

    private var selectedBook: BookSummary? {
        guard let selectedBookId else { return nil }
        return viewModel.books.first { $0.id == selectedBookId }
    }

    private var actionErrorPresented: Binding<Bool> {
        Binding(
            get: { actionError != nil },
            set: { if !$0 { actionError = nil } }
        )
    }

    private func presentExport(for book: BookSummary) {
        exportIncludeNotes = false
        bookPendingExport = book
    }

    private var batchDeleteTitle: String {
        if let count = batchDeleteCount {
            return "确定删除 \(count) 本书？"
        }
        return "确定删除书籍？"
    }

    private var selectionToolbar: some View {
        LibrarySelectionToolbar(
            selectedCount: checkedBookIds.count,
            startableCount: startableCheckedCount,
            stoppableCount: stoppableCheckedCount,
            summarizeActionInFlight: summarizeActionInFlight,
            onStartSummarize: { Task { await batchStartSummarize() } },
            onStopSummarize: { Task { await batchStopSummarize() } },
            onDelete: { batchDeleteCount = checkedBookIds.count },
            onFavorite: { Task { await batchSetFavorite(isFavorite: true) } },
            onUnfavorite: { Task { await batchSetFavorite(isFavorite: false) } },
            onSelectActive: { selectActiveSummarizeBooks() },
            onSelectStartable: { selectStartableBooks() },
            onSelectAll: { checkedBookIds = Set(viewModel.displayedBooks.map(\.id)) },
            onDone: { exitSelectionMode() }
        )
    }

    private var libraryControls: some View {
        HStack(spacing: 8) {
            filterPicker
            summarizeStateFilterPicker
            sortPicker
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
    }

    private var summarizeStateFilterPicker: some View {
        Picker("摘要状态", selection: $viewModel.summarizeStateFilter) {
            ForEach(SummarizeStateFilter.allCases) { item in
                Label(item.label, systemImage: item.systemImage).tag(item)
            }
        }
        .pickerStyle(.menu)
        .labelsHidden()
        .frame(maxWidth: .infinity, alignment: .leading)
        .layoutPriority(1)
        .help("摘要状态：\(viewModel.summarizeStateFilter.label)")
    }

    private var filterPicker: some View {
        Picker("书籍类型", selection: $viewModel.filter) {
            ForEach(viewModel.filterOptions) { item in
                Label(item.label, systemImage: item.systemImage).tag(item)
            }
        }
        .pickerStyle(.menu)
        .labelsHidden()
        .frame(maxWidth: .infinity, alignment: .leading)
        .layoutPriority(1)
        .help("书籍类型：\(viewModel.filter.label)")
        .onChange(of: viewModel.filter) { _, new in
            Task {
                do { try await viewModel.setFilter(new, using: core) }
                catch { setActionError(from: error) }
            }
        }
    }

    private var sortPicker: some View {
        Menu {
            ForEach(LibrarySort.allCases) { item in
                Button {
                    Task {
                        do { try await viewModel.setSort(item, using: core) }
                        catch { setActionError(from: error) }
                    }
                } label: {
                    if item == viewModel.sort {
                        Label(item.label, systemImage: "checkmark")
                    } else {
                        Text(item.label)
                    }
                }
            }
        } label: {
            Image(systemName: "arrow.up.arrow.down")
                .font(.caption)
                .foregroundStyle(LuminaTheme.textSecondary)
        }
        .fixedSize()
        .help("排序：\(viewModel.sort.label)")
    }

    @ViewBuilder
    private var bookList: some View {
        List {
            ForEach(viewModel.displayedBooks) { book in
                bookRow(book, selectionMode: isSelectionMode)
                    .tag(book.id)
            }
        }
        .listStyle(.plain)
    }

    @ViewBuilder
    private func bookRow(_ book: BookSummary, selectionMode: Bool) -> some View {
        let isSelected = !selectionMode && book.id == selectedBookId
        let row = BookRow(
            book: book,
            isClassifying: viewModel.classifyingIds.contains(book.id),
            ingestProgress: viewModel.ingestProgress[book.id],
            isSelectionMode: selectionMode,
            isChecked: checkedBookIds.contains(book.id),
            onToggleCheck: { toggleCheck(book.id) },
            onToggleFavorite: {
                Task {
                    do { try await viewModel.toggleFavorite(book, using: core) }
                    catch { setActionError(from: error) }
                }
            },
            onReclassify: {
                Task {
                    do { try await viewModel.reclassify(id: book.id, using: core) }
                    catch { setActionError(from: error) }
                }
            },
            onExport: {
                presentExport(for: book)
            },
            onDelete: {
                bookPendingDelete = book
            },
            onStartSummarize: {
                Task { await startSummarize(for: book.id) }
            },
            onStopSummarize: {
                Task { await stopSummarize(for: book.id) }
            }
        )

        Group {
            if selectionMode {
                row
                    .contentShape(Rectangle())
                    .onTapGesture { toggleCheck(book.id) }
            } else {
                Button {
                    selectedBookId = book.id
                } label: {
                    row
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
        .listRowBackground(isSelected ? LuminaTheme.libraryRowSelectionBackground : Color.clear)
        .listRowInsets(EdgeInsets(top: 6, leading: 10, bottom: 6, trailing: 10))
    }

    func refreshBooks(preserveOrder: Bool = false) async {
        guard await sidecar.waitUntilReady() else { return }
        do {
            try await viewModel.refresh(using: core, preserveOrder: preserveOrder)
            syncCheckedBooks()
        } catch {
            setActionError(from: error)
        }
    }

    private func syncCheckedBooks() {
        let validIds = Set(viewModel.books.map(\.id))
        checkedBookIds = checkedBookIds.intersection(validIds)
        if viewModel.books.isEmpty {
            exitSelectionMode()
        }
    }

    private var startableCheckedCount: Int {
        checkedStartableBookIds.count
    }

    private var stoppableCheckedCount: Int {
        checkedStoppableBookIds.count
    }

    private var checkedStartableBookIds: [String] {
        viewModel.books
            .filter { checkedBookIds.contains($0.id) && $0.canStartSummarize }
            .map(\.id)
    }

    private var checkedStoppableBookIds: [String] {
        viewModel.books
            .filter { checkedBookIds.contains($0.id) && $0.canStopSummarize }
            .map(\.id)
    }

    private func pollSummaryProgress() async {
        while !Task.isCancelled {
            guard viewModel.needsSummarizePolling else { return }
            try? await Task.sleep(nanoseconds: 3_000_000_000)
            guard !Task.isCancelled, viewModel.needsSummarizePolling else { return }
            await refreshBooks(preserveOrder: true)
        }
    }

    private func stopAllSummarize() async {
        guard !summarizeActionInFlight else { return }
        summarizeActionInFlight = true
        defer { summarizeActionInFlight = false }
        do {
            try await core.stopSummarizeAll()
            await refreshBooks(preserveOrder: true)
        } catch {
            setActionError(from: error)
        }
    }

    private func batchStartSummarize() async {
        let ids = checkedStartableBookIds
        guard !ids.isEmpty else { return }
        await runSummarizeBatch(ids: ids, start: true)
    }

    private func batchStopSummarize() async {
        let ids = checkedStoppableBookIds
        guard !ids.isEmpty else { return }
        await runSummarizeBatch(ids: ids, start: false)
    }

    private func startSummarize(for bookId: String) async {
        await runSummarizeBatch(ids: [bookId], start: true)
    }

    private func stopSummarize(for bookId: String) async {
        await runSummarizeBatch(ids: [bookId], start: false)
    }

    private func runSummarizeBatch(ids: [String], start: Bool) async {
        guard !summarizeActionInFlight else { return }
        summarizeActionInFlight = true
        defer { summarizeActionInFlight = false }
        do {
            if start {
                try await core.startSummarize(bookIds: ids)
            } else {
                try await core.stopSummarize(bookIds: ids)
            }
            await refreshBooks(preserveOrder: true)
        } catch {
            setActionError(from: error)
        }
    }

    private func selectActiveSummarizeBooks() {
        let ids = viewModel.displayedBooks
            .filter(\.canStopSummarize)
            .map(\.id)
        checkedBookIds.formUnion(ids)
    }

    private func selectStartableBooks() {
        let ids = viewModel.displayedBooks
            .filter(\.canStartSummarize)
            .map(\.id)
        checkedBookIds.formUnion(ids)
    }

    private func confirmDelete(_ book: BookSummary) async {
        bookPendingDelete = nil
        do {
            try await viewModel.deleteBook(id: book.id, using: core)
            if selectedBookId == book.id {
                selectedBookId = nil
            }
            syncCheckedBooks()
        } catch {
            setActionError(from: error)
        }
    }

    private func confirmBatchDelete(_ ids: [String]) async {
        guard !ids.isEmpty else { return }
        do {
            try await viewModel.deleteBooks(ids: ids, using: core)
            if let selected = selectedBookId, ids.contains(selected) {
                selectedBookId = nil
            }
            checkedBookIds.subtract(ids)
            if checkedBookIds.isEmpty && isSelectionMode && viewModel.books.isEmpty {
                exitSelectionMode()
            }
        } catch {
            setActionError(from: error)
        }
    }

    private func batchSetFavorite(isFavorite: Bool) async {
        let ids = Array(checkedBookIds)
        guard !ids.isEmpty else { return }
        do {
            try await viewModel.setFavorite(ids: ids, isFavorite: isFavorite, using: core)
        } catch {
            setActionError(from: error)
        }
    }

    private func toggleSelectionMode() {
        if isSelectionMode {
            exitSelectionMode()
        } else {
            isSelectionMode = true
        }
    }

    private func exitSelectionMode() {
        isSelectionMode = false
        checkedBookIds = []
    }

    private func toggleCheck(_ id: String) {
        if checkedBookIds.contains(id) {
            checkedBookIds.remove(id)
        } else {
            checkedBookIds.insert(id)
        }
    }

    private func setActionError(from error: Error) {
        actionError = ConnectionError.userMessage(for: error)
    }
}
