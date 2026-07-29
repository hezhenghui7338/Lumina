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
    @State private var showExport = false
    @State private var exportIncludeNotes = false
    @State private var exportSuccessURL: URL?
    @State private var pendingExport: PendingBookExport?
    @State private var showExportCancelled = false

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
            await refreshBooks()
        }
        .task(id: viewModel.books.map(\.id)) {
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
        .alert("出错了", isPresented: .constant(actionError != nil)) {
            Button("好") { actionError = nil }
        } message: {
            Text(actionError ?? "")
        }
        .alert("导出成功", isPresented: exportSuccessPresented) {
            Button("在 Finder 中显示") {
                if let url = exportSuccessURL {
                    NSWorkspace.shared.activateFileViewerSelecting([url])
                }
            }
            Button("好", role: .cancel) {
                exportSuccessURL = nil
            }
        } message: {
            if let url = exportSuccessURL {
                Text("已保存至\n\(url.path)")
            }
        }
        .alert("已取消保存", isPresented: $showExportCancelled) {
            Button("好", role: .cancel) {}
        }
        .sheet(isPresented: $showExport) {
            if let book = bookPendingExport {
                ExportSheet(
                    isPresented: $showExport,
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
                        pendingExport = PendingBookExport(
                            markdown: markdown,
                            bookTitle: book.title
                        )
                    },
                    onError: { actionError = $0 }
                )
            }
        }
        .onChange(of: showExport) { _, isShowing in
            guard !isShowing else { return }
            guard let pending = pendingExport else { return }
            pendingExport = nil
            Task { await finishExportSave(pending) }
        }
    }

    @MainActor
    private func finishExportSave(_ pending: PendingBookExport) async {
        try? await Task.sleep(nanoseconds: 150_000_000)
        do {
            switch try await BookMarkdownExporter.presentSavePanel(
                markdown: pending.markdown,
                bookTitle: pending.bookTitle
            ) {
            case .saved(let url):
                exportSuccessURL = url
            case .cancelled:
                showExportCancelled = true
            }
        } catch {
            actionError = error.localizedDescription
        }
    }

    private var selectedBook: BookSummary? {
        guard let selectedBookId else { return nil }
        return viewModel.books.first { $0.id == selectedBookId }
    }

    private var exportSuccessPresented: Binding<Bool> {
        Binding(
            get: { exportSuccessURL != nil },
            set: { if !$0 { exportSuccessURL = nil } }
        )
    }

    private func presentExport(for book: BookSummary) {
        bookPendingExport = book
        exportIncludeNotes = false
        showExport = true
    }

    private var batchDeleteTitle: String {
        if let count = batchDeleteCount {
            return "确定删除 \(count) 本书？"
        }
        return "确定删除书籍？"
    }

    private var selectionToolbar: some View {
        HStack(spacing: 8) {
            Button("删除 (\(checkedBookIds.count))") {
                batchDeleteCount = checkedBookIds.count
            }
            .font(.caption)
            .buttonStyle(.bordered)
            .controlSize(.small)
            .disabled(checkedBookIds.isEmpty)

            Button("收藏 (\(checkedBookIds.count))") {
                Task { await batchSetFavorite(isFavorite: true) }
            }
            .font(.caption)
            .buttonStyle(.bordered)
            .controlSize(.small)
            .disabled(checkedBookIds.isEmpty)

            Button("取消收藏 (\(checkedBookIds.count))") {
                Task { await batchSetFavorite(isFavorite: false) }
            }
            .font(.caption)
            .buttonStyle(.bordered)
            .controlSize(.small)
            .disabled(checkedBookIds.isEmpty)

            Spacer(minLength: 0)

            Button("全选") {
                checkedBookIds = Set(viewModel.books.map(\.id))
            }
            .font(.caption)
            .buttonStyle(.plain)

            Button("完成") {
                exitSelectionMode()
            }
            .font(.caption)
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
    }

    private var libraryControls: some View {
        VStack(alignment: .leading, spacing: 10) {
            Picker("集合", selection: $viewModel.collection) {
                ForEach(LibraryCollection.allCases) { item in
                    Text(item.label).tag(item)
                }
            }
            .pickerStyle(.segmented)
            .onChange(of: viewModel.collection) { _, _ in
                viewModel.persistPreferences()
                Task {
                    do { try await viewModel.refresh(using: core) }
                    catch { setActionError(from: error) }
                }
            }

            Menu {
                Picker("排序", selection: $viewModel.sort) {
                    ForEach(LibrarySort.allCases) { item in
                        Text(item.label).tag(item)
                    }
                }
            } label: {
                Label(viewModel.sort.label, systemImage: "arrow.up.arrow.down")
                    .font(.caption)
                    .foregroundStyle(LuminaTheme.textSecondary)
            }
            .onChange(of: viewModel.sort) { _, _ in
                viewModel.persistPreferences()
                Task {
                    do { try await viewModel.refresh(using: core) }
                    catch { setActionError(from: error) }
                }
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
    }

    @ViewBuilder
    private var bookList: some View {
        if isSelectionMode {
            List(viewModel.books) { book in
                bookRow(book, selectionMode: true)
            }
            .listStyle(.sidebar)
        } else {
            List(viewModel.books, selection: $selectedBookId) { book in
                bookRow(book, selectionMode: false)
                    .tag(book.id as String?)
            }
            .listStyle(.sidebar)
        }
    }

    @ViewBuilder
    private func bookRow(_ book: BookSummary, selectionMode: Bool) -> some View {
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
            }
        )

        if selectionMode {
            row
                .contentShape(Rectangle())
                .onTapGesture { toggleCheck(book.id) }
        } else {
            row
        }
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

    private func pollSummaryProgress() async {
        while !Task.isCancelled {
            guard viewModel.hasIncompleteSummaries else { return }
            try? await Task.sleep(nanoseconds: 3_000_000_000)
            guard !Task.isCancelled, viewModel.hasIncompleteSummaries else { return }
            await refreshBooks(preserveOrder: true)
        }
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
