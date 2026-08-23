import SwiftUI

struct LibraryRecentsView: View {
    @ObservedObject var viewModel: LibraryViewModel
    @Binding var selectedBookId: String?
    @EnvironmentObject private var core: CoreClient

    @State private var bookPendingDelete: BookSummary?
    @State private var actionError: String?

    var body: some View {
        VStack(spacing: 0) {
            if viewModel.recentBooks.isEmpty {
                ContentUnavailableView {
                    Label("暂无最近阅读", systemImage: "clock")
                } description: {
                    Text("打开一本书后会出现在这里")
                }
            } else {
                List {
                    ForEach(viewModel.recentBooks) { book in
                        recentsRow(book)
                    }
                }
                .listStyle(.plain)
            }
        }
        .navigationTitle("最近")
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
        .alert("出错了", isPresented: Binding(
            get: { actionError != nil },
            set: { if !$0 { actionError = nil } }
        )) {
            Button("好") { actionError = nil }
        } message: {
            Text(actionError ?? "")
        }
    }

    @ViewBuilder
    private func recentsRow(_ book: BookSummary) -> some View {
        let isSelected = book.id == selectedBookId
        Button {
            selectedBookId = book.id
        } label: {
            BookRow(
                book: book,
                isClassifying: viewModel.classifyingIds.contains(book.id),
                ingestProgress: viewModel.ingestProgress[book.id],
                onToggleFavorite: {
                    Task {
                        do { try await viewModel.toggleFavorite(book, using: core) }
                        catch { actionError = ConnectionError.userMessage(for: error) }
                    }
                },
                onReclassify: {
                    Task {
                        do { try await viewModel.reclassify(id: book.id, using: core) }
                        catch { actionError = ConnectionError.userMessage(for: error) }
                    }
                },
                onExport: {},
                onDelete: { bookPendingDelete = book },
                onStartSummarize: { tier in
                    Task { await startSummarize(bookId: book.id, tier: tier) }
                },
                onStopSummarize: {
                    Task { await stopSummarize(bookId: book.id) }
                }
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .listRowBackground(isSelected ? LuminaTheme.libraryRowSelectionBackground : Color.clear)
        .listRowInsets(EdgeInsets(top: 6, leading: 10, bottom: 6, trailing: 10))
    }

    private func confirmDelete(_ book: BookSummary) async {
        bookPendingDelete = nil
        do {
            try await viewModel.deleteBook(id: book.id, using: core)
            if selectedBookId == book.id {
                selectedBookId = nil
            }
        } catch {
            actionError = ConnectionError.userMessage(for: error)
        }
    }

    private func startSummarize(bookId: String, tier: SummaryTier) async {
        do {
            try await core.startSummarize(bookIds: [bookId], summaryTier: tier)
            try await viewModel.refresh(using: core, preserveOrder: true)
        } catch {
            actionError = ConnectionError.userMessage(for: error)
        }
    }

    private func stopSummarize(bookId: String) async {
        do {
            try await core.stopSummarize(bookIds: [bookId])
            try await viewModel.refresh(using: core, preserveOrder: true)
        } catch {
            actionError = ConnectionError.userMessage(for: error)
        }
    }
}
