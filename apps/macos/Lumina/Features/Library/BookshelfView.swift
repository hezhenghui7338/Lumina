import SwiftUI
import UniformTypeIdentifiers
import AppKit

struct BookshelfView: View {
    @EnvironmentObject private var core: CoreClient
    @ObservedObject var viewModel: LibraryViewModel
    @Binding var selectedBookId: String?

    var onImport: () -> Void
    var onImportPaths: ([String]) -> Void
    var onSearch: () -> Void
    var onShowAllNotes: () -> Void
    var onStartSummarize: (SummaryTier) -> Void
    var onStopSummarize: () -> Void

    @State private var bookPendingDelete: BookSummary?
    @State private var bookPendingRename: BookSummary?
    @State private var showRenameAlert = false
    @State private var renameDraft = ""
    @State private var actionError: String?
    @State private var isSelectionMode = false
    @State private var checkedBookIds: Set<String> = []
    @State private var batchDeleteCount: Int?
    @State private var bookPendingExport: BookSummary?
    @State private var bookPendingResegment: BookSummary?
    @State private var resegmentTargetChars = 4000
    @State private var resegmentTier: SegmentTier = .normal
    @State private var isResegmentSubmitting = false
    @State private var exportIncludeNotes = false
    @State private var exportMode = MarkdownExportMode.full
    @State private var exportDocument = MarkdownExportDocument(text: "")
    @State private var showFileExporter = false
    @State private var exportDefaultFilename = "summary.md"
    @State private var exportFallbackBookTitle = ""
    @State private var shouldPresentFileExporter = false
    @State private var exportFeedback: ExportFeedback?
    @State private var summarizeActionInFlight = false
    @State private var showAdvancedStartConfirm = false
    @State private var showSummarizePopover = false
    @State private var dropTargeted = false

    var body: some View {
        VStack(spacing: 0) {
            bookshelfControls
            if isSelectionMode {
                selectionToolbar
                Divider()
            }
            Group {
                if viewModel.matchedBooks.isEmpty {
                    emptyState
                } else if viewModel.viewMode == .grid {
                    bookGrid
                } else {
                    bookList
                }
            }
            .tourAnchor(.bookshelf)
            .background(dropTargeted ? LuminaTheme.accentMuted.opacity(0.45) : Color.clear)
            if viewModel.showsPagination {
                paginationBar
            }
        }
        .navigationTitle(viewModel.query.title)
        .toolbar { toolbarContent }
        .onChange(of: viewModel.pagedBooks.map(\.id)) { _, _ in
            syncCheckedBooks()
        }
        .onChange(of: viewModel.titleQuery) { _, _ in
            viewModel.resetPage()
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
            Button("取消", role: .cancel) { bookPendingDelete = nil }
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
            Button("取消", role: .cancel) { batchDeleteCount = nil }
        } message: {
            Text("将删除本地副本、摘要与笔记，且不可恢复。")
        }
        .alert("重命名", isPresented: $showRenameAlert) {
            TextField("书名", text: $renameDraft)
            Button("保存") {
                Task { await confirmRename() }
            }
            Button("取消", role: .cancel) {}
        }
        .alert("出错了", isPresented: Binding(
            get: { actionError != nil },
            set: { if !$0 { actionError = nil } }
        )) {
            Button("好") { actionError = nil }
        } message: {
            Text(actionError ?? "")
        }
        .confirmationDialog(
            "高级摘要",
            isPresented: $showAdvancedStartConfirm,
            titleVisibility: .visible
        ) {
            Button("开始高级摘要") { onStartSummarize(.advanced) }
            Button("取消", role: .cancel) {}
        } message: {
            Text("将用高级模型补齐尚未摘要的段落，消耗更多计算与 API。已有摘要不会被覆盖。")
        }
        .exportFeedbackAlert($exportFeedback)
        .sheet(item: $bookPendingExport, onDismiss: presentFileExporterIfNeeded) { book in
            ExportSheet(
                isPresented: Binding(
                    get: { bookPendingExport != nil },
                    set: { if !$0 { bookPendingExport = nil } }
                ),
                includeNotes: $exportIncludeNotes,
                mode: $exportMode,
                summaryReadyCount: book.summaryReady,
                summaryTotalCount: book.summaryTotal,
                onFetchMarkdown: {
                    try await BookMarkdownExporter.fetchMarkdown(
                        core: core,
                        bookId: book.id,
                        summaryReadyCount: book.summaryReady,
                        includeNotes: exportIncludeNotes,
                        mode: exportMode
                    )
                },
                onMarkdownReady: { markdown in
                    exportDocument = MarkdownExportDocument(text: markdown)
                    exportDefaultFilename = BookMarkdownExporter.defaultFilename(
                        for: book.title,
                        mode: exportMode
                    )
                    exportFallbackBookTitle = book.title
                    shouldPresentFileExporter = true
                    bookPendingExport = nil
                },
                onError: { actionError = $0 }
            )
        }
        .sheet(item: $bookPendingResegment) { book in
            ResegmentBookSheet(
                bookTitle: book.title,
                targetChars: $resegmentTargetChars,
                segmentTier: $resegmentTier,
                isPresented: Binding(
                    get: { bookPendingResegment != nil },
                    set: { if !$0 { bookPendingResegment = nil } }
                ),
                isSubmitting: isResegmentSubmitting,
                onSubmit: { submitResegment(book) }
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

    @ToolbarContentBuilder
    private var toolbarContent: some ToolbarContent {
        ToolbarItem(placement: .primaryAction) {
            Button(action: onImport) {
                Label("导入", systemImage: "square.and.arrow.down")
            }
            .help("导入书籍")
            .labelStyle(.iconOnly)
            .foregroundStyle(LuminaTheme.accent)
        }
        ToolbarItemGroup(placement: .automatic) {
            if let overview = viewModel.summarizeOverview,
               SummarizeActivityChip.shouldShow(activeCount: overview.activeCount) {
                SummarizeActivityChip(
                    running: overview.counts.running,
                    queued: overview.counts.queued,
                    indexing: overview.indexingCount,
                    stalledReason: overview.stalled_reason,
                    isBusy: summarizeActionInFlight,
                    onStatusTap: {
                        viewModel.selectFacet(
                            SummarizeActivityNavigationPolicy.destinationCollection
                        )
                    }
                ) {
                    Task { await stopAllSummarize() }
                }
                .disabled(summarizeActionInFlight)
            }

            if !viewModel.matchedBooks.isEmpty {
                Button { toggleSelectionMode() } label: {
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

            Button {
                showSummarizePopover.toggle()
            } label: {
                Label("摘要", systemImage: "text.alignleft")
            }
            .popover(isPresented: $showSummarizePopover, arrowEdge: .bottom) {
                VStack(alignment: .leading, spacing: 4) {
                    SummarizeChevronSplit(title: "全部开始摘要") {
                        showSummarizePopover = false
                        onStartSummarize(.normal)
                    } advancedMenu: {
                        Button("高级摘要（仅未摘要）") {
                            showSummarizePopover = false
                            showAdvancedStartConfirm = true
                        }
                    }
                    Button("全部停止摘要", action: {
                        showSummarizePopover = false
                        onStopSummarize()
                    })
                    .buttonStyle(.plain)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 6)
                }
                .padding(10)
            }
            .help("点「全部开始摘要」立即正常档；点旁边箭头才展开高级（悬停不弹出）")
        }
    }

    private var bookshelfControls: some View {
        HStack(spacing: 10) {
            TextField("筛选书名", text: $viewModel.titleQuery)
                .textFieldStyle(.roundedBorder)
                .frame(maxWidth: 240)
            Picker("排序", selection: sortBinding) {
                ForEach(LibrarySort.allCases) { item in
                    Text(item.label).tag(item)
                }
            }
            .pickerStyle(.menu)
            .frame(maxWidth: 140)
            Picker("顺序", selection: orderBinding) {
                ForEach(LibrarySortOrder.allCases) { item in
                    Text(item.label).tag(item)
                }
            }
            .pickerStyle(.segmented)
            .frame(maxWidth: 140)
            .help("升序：旧→新、A→Z、少→多、未收藏在前；降序相反")
            Picker("视图", selection: viewModeBinding) {
                ForEach(BookshelfViewMode.allCases) { mode in
                    Label(mode.label, systemImage: mode.systemImage).tag(mode)
                }
            }
            .pickerStyle(.segmented)
            .frame(maxWidth: 140)
            Spacer()
            Text("\(viewModel.matchedBooks.count) 本")
                .font(.caption)
                .foregroundStyle(LuminaTheme.textSecondary)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
    }

    private var sortBinding: Binding<LibrarySort> {
        Binding(
            get: { viewModel.sort },
            set: { viewModel.setSort($0) }
        )
    }

    private var orderBinding: Binding<LibrarySortOrder> {
        Binding(
            get: { viewModel.sortOrder },
            set: { viewModel.setSortOrder($0) }
        )
    }

    private var viewModeBinding: Binding<BookshelfViewMode> {
        Binding(
            get: { viewModel.viewMode },
            set: { viewModel.setViewMode($0) }
        )
    }

    private var paginationBar: some View {
        HStack(spacing: 12) {
            Button {
                viewModel.setPage(viewModel.pageIndex - 1)
            } label: {
                Label("上一页", systemImage: "chevron.left")
            }
            .disabled(viewModel.pageIndex <= 0 || viewModel.pageCount <= 1)

            Text("第 \(viewModel.pageIndex + 1) / \(max(viewModel.pageCount, 1)) 页")
                .font(.caption)
                .foregroundStyle(LuminaTheme.textSecondary)
                .monospacedDigit()

            Button {
                viewModel.setPage(viewModel.pageIndex + 1)
            } label: {
                Label("下一页", systemImage: "chevron.right")
            }
            .disabled(viewModel.pageIndex >= viewModel.pageCount - 1 || viewModel.pageCount <= 1)

            Spacer(minLength: 8)

            Picker("每页", selection: pageSizeBinding) {
                ForEach(BookshelfPaging.allowedPageSizes, id: \.self) { size in
                    Text("\(size)").tag(size)
                }
            }
            .pickerStyle(.menu)
            .labelsHidden()
            .frame(maxWidth: 72)
            .help("每页显示数量")
            Text("本/页")
                .font(.caption)
                .foregroundStyle(LuminaTheme.textSecondary)
        }
        .buttonStyle(.borderless)
        .padding(.horizontal, 16)
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity)
        .background(.bar)
    }

    private var pageSizeBinding: Binding<Int> {
        Binding(
            get: { viewModel.pageSize },
            set: { viewModel.setPageSize($0) }
        )
    }

    private var emptyState: some View {
        ContentUnavailableView {
            Label(
                viewModel.books.isEmpty ? "书架是空的" : "没有符合筛选的书",
                systemImage: "books.vertical"
            )
        } description: {
            Text(viewModel.books.isEmpty
                 ? "导入电子书，或把文件拖到这里"
                 : "试试其他筛选，或导入新书")
        } actions: {
            Button(action: onImport) {
                Label("导入书籍", systemImage: "square.and.arrow.down")
            }
            .buttonStyle(.borderedProminent)
            .tint(LuminaTheme.accent)
            .tourAnchor(.importButton)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var bookGrid: some View {
        ScrollView {
            LazyVGrid(
                columns: [GridItem(.adaptive(minimum: 148), spacing: 16)],
                spacing: 20
            ) {
                ForEach(viewModel.pagedBooks) { book in
                    BookCard(
                        book: book,
                        isClassifying: viewModel.classifyingIds.contains(book.id),
                        ingestProgress: viewModel.ingestProgress[book.id],
                        isSelectionMode: isSelectionMode,
                        isChecked: checkedBookIds.contains(book.id),
                        onToggleCheck: { toggleCheck(book.id) },
                        onOpen: { openBook(book) },
                        onToggleFavorite: { Task { await toggleFavorite(book) } },
                        onRename: { presentRename(book) },
                        onReclassify: { Task { await reclassify(book.id) } },
                        onResegment: { presentResegment(for: book) },
                        onExport: { presentExport(for: book) },
                        onDelete: { bookPendingDelete = book },
                        onStartSummarize: { tier in
                            Task { await startSummarize(for: book.id, summaryTier: tier) }
                        },
                        onStopSummarize: {
                            Task { await stopSummarize(for: book.id) }
                        }
                    )
                }
            }
            .padding(20)
        }
    }

    @ViewBuilder
    private var bookList: some View {
        List {
            ForEach(viewModel.pagedBooks) { book in
                listRow(book)
            }
        }
        .listStyle(.plain)
    }

    @ViewBuilder
    private func listRow(_ book: BookSummary) -> some View {
        let row = BookRow(
            book: book,
            isClassifying: viewModel.classifyingIds.contains(book.id),
            ingestProgress: viewModel.ingestProgress[book.id],
            isSelectionMode: isSelectionMode,
            isChecked: checkedBookIds.contains(book.id),
            onToggleCheck: { toggleCheck(book.id) },
            onToggleFavorite: { Task { await toggleFavorite(book) } },
            onRename: { presentRename(book) },
            onReclassify: { Task { await reclassify(book.id) } },
            onResegment: { presentResegment(for: book) },
            onExport: { presentExport(for: book) },
            onDelete: { bookPendingDelete = book },
            onStartSummarize: { tier in
                Task { await startSummarize(for: book.id, summaryTier: tier) }
            },
            onStopSummarize: {
                Task { await stopSummarize(for: book.id) }
            }
        )

        Group {
            if isSelectionMode {
                row
                    .contentShape(Rectangle())
                    .onTapGesture { toggleCheck(book.id) }
            } else {
                Button { openBook(book) } label: {
                    row.contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
        .listRowInsets(EdgeInsets(top: 6, leading: 10, bottom: 6, trailing: 10))
    }

    private var selectionToolbar: some View {
        LibrarySelectionToolbar(
            selectedCount: checkedBookIds.count,
            startableCount: startableCheckedCount,
            stoppableCount: stoppableCheckedCount,
            summarizeActionInFlight: summarizeActionInFlight,
            onStartSummarize: { tier in
                Task { await batchStartSummarize(summaryTier: tier) }
            },
            onStopSummarize: { Task { await batchStopSummarize() } },
            onDelete: { batchDeleteCount = checkedBookIds.count },
            onFavorite: { Task { await batchSetFavorite(isFavorite: true) } },
            onUnfavorite: { Task { await batchSetFavorite(isFavorite: false) } },
            onSelectActive: { selectActiveSummarizeBooks() },
            onSelectStartable: { selectStartableBooks() },
            onSelectAll: { checkedBookIds = Set(viewModel.pagedBooks.map(\.id)) },
            onDone: { exitSelectionMode() }
        )
    }

    private func openBook(_ book: BookSummary) {
        if !book.canOpenInReader {
            actionError = book.statusLabel
            return
        }
        selectedBookId = book.id
    }

    private func presentExport(for book: BookSummary) {
        exportIncludeNotes = false
        exportMode = .full
        bookPendingExport = book
    }

    private func presentResegment(for book: BookSummary) {
        guard book.canResegment else { return }
        resegmentTargetChars = ResegmentTarget.normalized(
            currentTarget: book.chunk_target_chars,
            totalChars: book.total_char_count,
            segmentCount: book.segment_count ?? 0
        )
        resegmentTier = .normal
        bookPendingResegment = book
    }

    private func submitResegment(_ book: BookSummary) {
        guard !isResegmentSubmitting else { return }
        isResegmentSubmitting = true
        Task {
            do {
                try await viewModel.resegmentBook(
                    book,
                    chunkTargetChars: resegmentTargetChars,
                    segmentTier: resegmentTier,
                    using: core
                )
                bookPendingResegment = nil
            } catch {
                actionError = ConnectionError.userMessage(for: error)
            }
            isResegmentSubmitting = false
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
                bookTitle: bookTitle,
                mode: exportMode
            )
        }
    }

    private var batchDeleteTitle: String {
        if let count = batchDeleteCount {
            return "确定删除 \(count) 本书？"
        }
        return "确定删除书籍？"
    }

    private func syncCheckedBooks() {
        let validIds = Set(viewModel.matchedBooks.map(\.id))
        checkedBookIds = checkedBookIds.intersection(validIds)
        if viewModel.matchedBooks.isEmpty {
            exitSelectionMode()
        }
    }

    private var startableCheckedCount: Int { checkedStartableBookIds.count }
    private var stoppableCheckedCount: Int { checkedStoppableBookIds.count }

    private var checkedStartableBookIds: [String] {
        viewModel.matchedBooks
            .filter { checkedBookIds.contains($0.id) && $0.canStartSummarize }
            .map(\.id)
    }

    private var checkedStoppableBookIds: [String] {
        viewModel.matchedBooks
            .filter { checkedBookIds.contains($0.id) && $0.canStopSummarize }
            .map(\.id)
    }

    private func stopAllSummarize() async {
        guard !summarizeActionInFlight else { return }
        summarizeActionInFlight = true
        defer { summarizeActionInFlight = false }
        do {
            try await core.stopSummarizeAll()
            try await viewModel.refresh(using: core, preserveOrder: true)
        } catch {
            actionError = ConnectionError.userMessage(for: error)
        }
    }

    private func batchStartSummarize(summaryTier: SummaryTier = .normal) async {
        let ids = checkedStartableBookIds
        guard !ids.isEmpty else { return }
        await runSummarizeBatch(ids: ids, start: true, summaryTier: summaryTier)
    }

    private func batchStopSummarize() async {
        let ids = checkedStoppableBookIds
        guard !ids.isEmpty else { return }
        await runSummarizeBatch(ids: ids, start: false)
    }

    private func startSummarize(for bookId: String, summaryTier: SummaryTier = .normal) async {
        await runSummarizeBatch(ids: [bookId], start: true, summaryTier: summaryTier)
    }

    private func stopSummarize(for bookId: String) async {
        await runSummarizeBatch(ids: [bookId], start: false)
    }

    private func runSummarizeBatch(
        ids: [String], start: Bool, summaryTier: SummaryTier = .normal
    ) async {
        guard !summarizeActionInFlight else { return }
        summarizeActionInFlight = true
        defer { summarizeActionInFlight = false }
        do {
            if start {
                try await core.startSummarize(bookIds: ids, summaryTier: summaryTier)
            } else {
                try await core.stopSummarize(bookIds: ids)
            }
            try await viewModel.refresh(using: core, preserveOrder: true)
        } catch {
            actionError = ConnectionError.userMessage(for: error)
        }
    }

    private func selectActiveSummarizeBooks() {
        checkedBookIds.formUnion(viewModel.pagedBooks.filter(\.canStopSummarize).map(\.id))
    }

    private func selectStartableBooks() {
        checkedBookIds.formUnion(viewModel.pagedBooks.filter(\.canStartSummarize).map(\.id))
    }

    private func confirmDelete(_ book: BookSummary) async {
        bookPendingDelete = nil
        do {
            try await viewModel.deleteBook(id: book.id, using: core)
            if selectedBookId == book.id { selectedBookId = nil }
            syncCheckedBooks()
        } catch {
            actionError = ConnectionError.userMessage(for: error)
        }
    }

    private func presentRename(_ book: BookSummary) {
        bookPendingRename = book
        renameDraft = book.title
        showRenameAlert = true
    }

    private func confirmRename() async {
        guard let book = bookPendingRename else { return }
        let title = renameDraft
        bookPendingRename = nil
        do {
            try await viewModel.renameBook(book, title: title, using: core)
        } catch {
            actionError = ConnectionError.userMessage(for: error)
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
            if checkedBookIds.isEmpty { exitSelectionMode() }
        } catch {
            actionError = ConnectionError.userMessage(for: error)
        }
    }

    private func batchSetFavorite(isFavorite: Bool) async {
        let ids = Array(checkedBookIds)
        guard !ids.isEmpty else { return }
        do {
            try await viewModel.setFavorite(ids: ids, isFavorite: isFavorite, using: core)
        } catch {
            actionError = ConnectionError.userMessage(for: error)
        }
    }

    private func toggleFavorite(_ book: BookSummary) async {
        do {
            try await viewModel.toggleFavorite(book, using: core)
        } catch {
            actionError = ConnectionError.userMessage(for: error)
        }
    }

    private func reclassify(_ id: String) async {
        do {
            try await viewModel.reclassify(id: id, using: core)
        } catch {
            actionError = ConnectionError.userMessage(for: error)
        }
    }

    private func toggleSelectionMode() {
        if isSelectionMode { exitSelectionMode() } else { isSelectionMode = true }
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

    private func handleDrop(providers: [NSItemProvider]) -> Bool {
        for provider in providers {
            provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier, options: nil) { item, _ in
                let url: URL?
                if let data = item as? Data {
                    url = URL(dataRepresentation: data, relativeTo: nil)
                } else {
                    url = item as? URL
                }
                guard let url, LibraryImportPolicy.isSupported(pathExtension: url.pathExtension) else {
                    return
                }
                DispatchQueue.main.async {
                    onImportPaths([url.path])
                }
            }
        }
        return true
    }
}
