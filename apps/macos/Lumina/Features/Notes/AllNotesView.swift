import SwiftUI

struct AllNotesView: View {
    @EnvironmentObject private var core: CoreClient
    var onSelectNote: (String, Int?) -> Void
    var onDismiss: (() -> Void)? = nil

    @State private var notes: [NoteRow] = []
    @State private var loading = false
    @State private var error: String?
    @State private var isSelectionMode = false
    @State private var checkedNoteIds: Set<String> = []
    @State private var notePendingDelete: NoteRow?
    @State private var batchDeleteCount: Int?

    var body: some View {
        Group {
            if loading && notes.isEmpty {
                ProgressView("加载笔记…")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let error, notes.isEmpty {
                ContentUnavailableView(
                    "笔记加载失败",
                    systemImage: "exclamationmark.triangle",
                    description: Text(error)
                )
            } else if notes.isEmpty {
                ContentUnavailableView(
                    "还没有笔记",
                    systemImage: "note.text",
                    description: Text("在阅读器右侧写笔记，或把深聊回答存为笔记。每条笔记都会挂在具体段落上。")
                )
            } else {
                VStack(spacing: 0) {
                    if isSelectionMode {
                        selectionToolbar
                        Divider()
                    }
                    List(notes) { note in
                        noteRow(note)
                    }
                    .listStyle(.plain)
                }
            }
        }
        .navigationTitle("全部笔记")
        .background(LuminaTheme.background)
        .toolbar { notesToolbar }
        .task { await reload() }
        .refreshable { await reload() }
        .confirmationDialog(
            "确定删除这条笔记？",
            isPresented: Binding(
                get: { notePendingDelete != nil },
                set: { if !$0 { notePendingDelete = nil } }
            ),
            titleVisibility: .visible
        ) {
            if notePendingDelete != nil {
                Button("删除", role: .destructive) {
                    if let note = notePendingDelete {
                        Task { await deleteNotes([note.id]) }
                    }
                    notePendingDelete = nil
                }
            }
            Button("取消", role: .cancel) {
                notePendingDelete = nil
            }
        } message: {
            Text("此操作不可恢复。")
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
                Button("删除 \(count) 条笔记", role: .destructive) {
                    let ids = Array(checkedNoteIds)
                    batchDeleteCount = nil
                    Task { await deleteNotes(ids) }
                }
            }
            Button("取消", role: .cancel) {
                batchDeleteCount = nil
            }
        } message: {
            Text("此操作不可恢复。")
        }
    }

    @ToolbarContentBuilder
    private var notesToolbar: some ToolbarContent {
        if let onDismiss {
            ToolbarItem(placement: .navigation) {
                Button("返回") { onDismiss() }
            }
        }
        if !notes.isEmpty {
            ToolbarItem(placement: .automatic) {
                Button {
                    toggleSelectionMode()
                } label: {
                    Image(systemName: isSelectionMode ? "checklist.checked" : "checklist")
                }
                .help(isSelectionMode ? "退出多选" : "多选")
            }
        }
    }

    private var selectionToolbar: some View {
        HStack(spacing: 8) {
            Button("删除 (\(checkedNoteIds.count))") {
                batchDeleteCount = checkedNoteIds.count
            }
            .font(.caption)
            .buttonStyle(.bordered)
            .controlSize(.small)
            .disabled(checkedNoteIds.isEmpty)

            Spacer(minLength: 0)

            Button("全选") {
                checkedNoteIds = Set(notes.map(\.id))
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

    private var batchDeleteTitle: String {
        if let count = batchDeleteCount {
            return "确定删除 \(count) 条笔记？"
        }
        return "确定删除笔记？"
    }

    @ViewBuilder
    private func noteRow(_ note: NoteRow) -> some View {
        HStack(alignment: .top, spacing: 8) {
            if isSelectionMode {
                Toggle(
                    isOn: Binding(
                        get: { checkedNoteIds.contains(note.id) },
                        set: { on in
                            if on {
                                checkedNoteIds.insert(note.id)
                            } else {
                                checkedNoteIds.remove(note.id)
                            }
                        }
                    )
                ) {
                    EmptyView()
                }
                .toggleStyle(.checkbox)
                .labelsHidden()
            }

            if isSelectionMode {
                noteContent(note)
                    .contentShape(Rectangle())
                    .onTapGesture { toggleCheck(note.id) }
            } else {
                Button {
                    onSelectNote(note.book_id, note.segment_index)
                } label: {
                    noteContent(note)
                }
                .buttonStyle(.plain)
                .contextMenu {
                    Button("删除", role: .destructive) {
                        notePendingDelete = note
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func noteContent(_ note: NoteRow) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(note.book_title ?? "未知书籍")
                    .font(.headline)
                Spacer()
                Text(typeLabel(note.type))
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            if let label = note.segment_label, !label.isEmpty {
                Text(label)
                    .font(.caption)
                    .foregroundStyle(LuminaTheme.accent)
            }
            Text(note.content)
                .font(.subheadline)
                .foregroundStyle(.primary)
                .lineLimit(3)
                .multilineTextAlignment(.leading)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func typeLabel(_ type: String) -> String {
        switch type {
        case "ai": return "AI"
        case "highlight": return "划线"
        default: return "手动"
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
        checkedNoteIds = []
    }

    private func toggleCheck(_ id: String) {
        if checkedNoteIds.contains(id) {
            checkedNoteIds.remove(id)
        } else {
            checkedNoteIds.insert(id)
        }
    }

    private func reload() async {
        loading = true
        defer { loading = false }
        do {
            notes = try await core.listNotes()
            error = nil
            let validIds = Set(notes.map(\.id))
            checkedNoteIds = checkedNoteIds.intersection(validIds)
            if notes.isEmpty {
                exitSelectionMode()
            }
        } catch is CancellationError {
            return
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func deleteNotes(_ ids: [String]) async {
        guard !ids.isEmpty else { return }
        do {
            try await core.deleteNotes(ids: ids)
            notes.removeAll { ids.contains($0.id) }
            checkedNoteIds.subtract(ids)
            if checkedNoteIds.isEmpty && isSelectionMode && notes.isEmpty {
                exitSelectionMode()
            }
        } catch is CancellationError {
            return
        } catch {
            self.error = error.localizedDescription
            await reload()
        }
    }
}
