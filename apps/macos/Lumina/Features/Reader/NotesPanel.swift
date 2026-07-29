import SwiftUI

private enum NotesFilter: String, CaseIterable, Identifiable {
    case current
    case all

    var id: String { rawValue }

    var title: String {
        switch self {
        case .current: return "当前段"
        case .all: return "全部"
        }
    }
}

struct NotesPanel: View {
    let bookId: String
    let segmentId: String?
    var refreshToken: Int = 0
    var onSelectSegment: ((Int) -> Void)?
    @EnvironmentObject private var core: CoreClient
    @State private var notes: [NoteRow] = []
    @State private var draft = ""
    @State private var error: String?
    @State private var filter: NotesFilter = .all
    @State private var isSelectionMode = false
    @State private var checkedNoteIds: Set<String> = []
    @State private var notePendingDelete: NoteRow?
    @State private var batchDeleteCount: Int?

    private var canCreate: Bool {
        segmentId != nil && !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            headerRow

            if isSelectionMode && !notes.isEmpty {
                selectionToolbar
            }

            Picker("筛选", selection: $filter) {
                ForEach(NotesFilter.allCases) { item in
                    Text(item.title).tag(item)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()

            TextField("写笔记…", text: $draft, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(2...4)
                .disabled(segmentId == nil)

            if segmentId == nil {
                Text("请先选择段落再写笔记")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            if notes.isEmpty {
                Text(emptyLabel)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 8) {
                        ForEach(notes) { note in
                            noteRow(note)
                        }
                    }
                }
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(LuminaTheme.surface)
        .task(id: taskKey) { await reload() }
        .alert("笔记错误", isPresented: Binding(
            get: { error != nil },
            set: { if !$0 { error = nil } }
        )) {
            Button("好") { error = nil }
        } message: {
            Text(error ?? "")
        }
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

    private var headerRow: some View {
        HStack {
            Text("笔记").font(.headline)
            Spacer()
            if !notes.isEmpty {
                Button {
                    toggleSelectionMode()
                } label: {
                    Image(systemName: isSelectionMode ? "checklist.checked" : "checklist")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(
                            isSelectionMode ? LuminaTheme.accent : LuminaTheme.textSecondary
                        )
                }
                .buttonStyle(.plain)
                .help(isSelectionMode ? "退出多选" : "多选")
            }
            Button("新建") { Task { await createNote() } }
                .disabled(!canCreate)
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
    }

    private var batchDeleteTitle: String {
        if let count = batchDeleteCount {
            return "确定删除 \(count) 条笔记？"
        }
        return "确定删除笔记？"
    }

    private var taskKey: String {
        "\(bookId)-\(segmentId ?? "")-\(filter.rawValue)-\(refreshToken)"
    }

    private var emptyLabel: String {
        filter == .current ? "当前段暂无笔记" : "暂无笔记"
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

            Group {
                if isSelectionMode {
                    noteCard(note)
                        .contentShape(Rectangle())
                        .onTapGesture { toggleCheck(note.id) }
                } else {
                    Button {
                        if let idx = note.segment_index {
                            onSelectSegment?(idx)
                        }
                    } label: {
                        noteCard(note)
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
    }

    @ViewBuilder
    private func noteCard(_ note: NoteRow) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            if let label = note.segment_label, !label.isEmpty {
                Text(label)
                    .font(.caption2)
                    .foregroundStyle(LuminaTheme.accent)
            }
            if let quote = note.quote, !quote.isEmpty {
                Text("「\(quote)」")
                    .font(.caption)
                    .foregroundStyle(LuminaTheme.accent)
            }
            Text(note.content)
                .font(.subheadline)
                .foregroundStyle(.primary)
                .multilineTextAlignment(.leading)
            Text(note.type)
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .luminaCard()
        .contentShape(Rectangle())
    }

    func saveFromChat(_ content: String, quote: String? = nil) async {
        draft = content
        await createNote(quote: quote, type: "ai")
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
        do {
            let filterSegmentId = filter == .current ? segmentId : nil
            if filter == .current && segmentId == nil {
                notes = []
                exitSelectionMode()
                return
            }
            notes = try await core.listNotes(bookId: bookId, segmentId: filterSegmentId)
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

    private func createNote(quote: String? = nil, type: String = "manual") async {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        guard let segmentId else {
            error = "请先选择段落"
            return
        }
        do {
            _ = try await core.createNote(
                bookId: bookId,
                content: text,
                segmentId: segmentId,
                quote: quote,
                type: type
            )
            draft = ""
            await reload()
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

struct NoteRow: Codable, Identifiable, Hashable {
    let id: String
    let book_id: String
    let segment_id: String
    let quote: String?
    let content: String
    let type: String
    let created_at: String
    let segment_index: Int?
    let segment_label: String?
    let book_title: String?
}
