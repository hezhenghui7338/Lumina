import SwiftUI

struct LibraryMetadataBook: Decodable, Identifiable {
    let id: String
    let title: String
    let author: String?
    let language: String?
    let category: String?
    let status: String?
    let segment_count: Int?
    let created_at: String?
    let last_opened_at: String?
    let reading_progress: Double?
    let summary_complete: Bool
    let highlight_count: Int
    let comment_count: Int
    let open_count: Int
    let published_year: Int?
    let description: String
    let tags: [String]
}

struct LibraryAskAction: Decodable {
    let kind: String
    let tag: String
    let book_count: Int
}

struct LibraryAskResponse: Decodable {
    let result_id: String?
    let total: Int
    var books: [LibraryMetadataBook]
    let answer: String
    let criteria: [String]
    var action: LibraryAskAction?
}

struct LibraryApplyResponse: Decodable {
    let book_count: Int
    let message: String
    let books: [LibraryMetadataBook]
}

struct LibraryTag: Decodable, Identifiable {
    let id: String
    let name: String
    let book_count: Int
}

struct LibraryTagsResponse: Decodable { let tags: [LibraryTag] }

struct AskLibraryView: View {
    @EnvironmentObject private var core: CoreClient
    @Environment(\.dismiss) private var dismiss
    var onOpenBook: (String) -> Void
    @State private var question = ""
    @State private var submittedQuestion = ""
    @State private var result: LibraryAskResponse?
    @State private var busy = false
    @State private var error: String?
    @State private var feedback: String?
    @State private var showTags = false
    @State private var tagDraft = ""
    @State private var removeTag = false
    @State private var task: Task<Void, Never>?
    @FocusState private var inputFocused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 10) {
                Image(systemName: "books.vertical.circle").font(.title).foregroundStyle(LuminaTheme.accent)
                VStack(alignment: .leading, spacing: 3) {
                    Text("问书库").font(.title2.bold())
                    Text("找找想读的书，顺手整理书架。")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button("管理标签") { showTags = true }
                Button("完成") { dismiss() }.keyboardShortcut(.cancelAction)
            }
            HStack {
                TextField(result == nil ? "例如：我有多少本英文书？" : "继续问，例如：其中哪些还没开始读？", text: $question)
                    .textFieldStyle(.roundedBorder).focused($inputFocused)
                    .onSubmit { ask() }
                Button { ask() } label: { Image(systemName: "arrow.up.circle.fill").font(.title2) }
                    .buttonStyle(.plain).foregroundStyle(LuminaTheme.accent)
                    .disabled(busy || question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                if result != nil {
                    Button("重新开始") { result = nil; submittedQuestion = ""; feedback = nil; error = nil }
                        .disabled(busy)
                }
            }
            if busy { ProgressView("正在查看书库…").controlSize(.small) }
            if let error { Text(error).foregroundStyle(.red).font(.callout).textSelection(.enabled) }
            if let feedback { Text(feedback).foregroundStyle(.secondary).font(.callout) }
            if let result {
                resultView(result)
            } else {
                VStack(alignment: .leading, spacing: 12) {
                    Text("可以这样问").font(.headline)
                    ForEach(["我有多少本英文书？", "我有多少本300段以下的书？", "我有哪些村上春树的书？", "哪些书划线最多？", "我最近读过哪些书？"], id: \.self) { example in
                        Button(example) { question = example; ask() }.buttonStyle(.link).disabled(busy)
                    }
                    Text("按书籍信息、阅读状态和标签查询。打开次数从启用功能后累计。")
                        .font(.caption).foregroundStyle(.secondary).padding(.top, 8)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading).padding(.top, 16)
            }
        }
        .padding(24).frame(minWidth: 680, idealWidth: 760, minHeight: 560, idealHeight: 680)
        .background(LuminaTheme.background)
        .sheet(isPresented: $showTags) {
            LibraryTagsView { name in
                question = "有哪些带“\(name)”标签的书？"
                ask()
            }
        }
        .onAppear { inputFocused = true }
        .onDisappear { task?.cancel() }
    }

    @ViewBuilder private func resultView(_ response: LibraryAskResponse) -> some View {
        Text(submittedQuestion).font(.caption).foregroundStyle(.secondary).lineLimit(2)
        Text(response.answer).font(.headline).textSelection(.enabled)
        if !response.criteria.isEmpty {
            Text(response.criteria.joined(separator: " · ")).font(.caption).foregroundStyle(.secondary)
        }
        if let action = response.action {
            HStack {
                Text("\(action.book_count) 本书 · \(action.kind == "add_tag" ? "添加" : "移除")标签「\(action.tag)」")
                Spacer()
                Button("应用标签") { apply(response) }
                    .buttonStyle(.borderedProminent).tint(LuminaTheme.accent)
                    .disabled(busy || action.book_count == 0)
            }.padding(12).background(LuminaTheme.accentMuted).clipShape(RoundedRectangle(cornerRadius: 8))
        }
        if response.total > 0 {
            HStack {
                TextField("为这 \(response.total) 本书设置标签", text: $tagDraft).textFieldStyle(.roundedBorder)
                Picker("操作", selection: $removeTag) {
                    Text("添加").tag(false)
                    Text("移除").tag(true)
                }.labelsHidden().frame(width: 85)
                Button("预览") { preview(response) }
                    .disabled(busy || tagDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 10) {
                ForEach(response.books) { book in
                    VStack(alignment: .leading, spacing: 7) {
                        HStack {
                            Button(book.title) { dismiss(); onOpenBook(book.id) }
                                .buttonStyle(.link).font(.headline)
                            Spacer()
                            Text(book.author ?? "作者未知").font(.caption).foregroundStyle(.secondary)
                        }
                        Text(details(book)).font(.caption).foregroundStyle(.secondary)
                        if !book.tags.isEmpty {
                            Text(book.tags.map { "#\($0)" }.joined(separator: "  ")).font(.caption).foregroundStyle(LuminaTheme.accent)
                        }
                        if !book.description.isEmpty { Text(book.description).font(.caption).lineLimit(3).foregroundStyle(.secondary) }
                    }.frame(maxWidth: .infinity, alignment: .leading).luminaCard()
                }
                if response.total > response.books.count {
                    Text("共 \(response.total) 本，展示前 \(response.books.count) 本；标签操作会应用到全部匹配书籍。可继续提问缩小范围。")
                        .font(.caption).foregroundStyle(.secondary)
                }
                if response.total == 0 { Text("换一个条件试试。正在整理中的信息可能还未齐全。 ").foregroundStyle(.secondary) }
            }
        }.disabled(busy)
        Text("阅读进度按当前位置估算；打开次数从启用功能后累计。出版年份缺失时不作推测。")
            .font(.caption2).foregroundStyle(.secondary)
    }

    private func details(_ book: LibraryMetadataBook) -> String {
        var parts = [book.language ?? "语言未知", book.category ?? "未分类", "\(book.segment_count ?? 0) 段",
                     book.summary_complete ? "摘要完成" : "摘要未完成",
                     "进度 \(Int(book.reading_progress ?? 0))%", "划线 \(book.highlight_count)", "评论 \(book.comment_count)", "打开 \(book.open_count) 次"]
        if let year = book.published_year { parts.append("\(year) 年出版") }
        if let created = book.created_at { parts.append("加入 \(created.prefix(10))") }
        return parts.joined(separator: " · ")
    }

    private func ask() {
        let text = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !busy, !text.isEmpty else { return }
        let previous = result?.result_id
        busy = true; error = nil; feedback = nil
        task = Task { @MainActor in
            defer { busy = false }
            do {
                let value = try await core.askLibrary(text, previousResultId: previous)
                try Task.checkCancellation()
                result = value; submittedQuestion = text; question = ""; inputFocused = true
            } catch { if !Task.isCancelled { self.error = error.localizedDescription } }
        }
    }

    private func preview(_ response: LibraryAskResponse) {
        guard let id = response.result_id, !busy else { return }
        busy = true; error = nil; feedback = nil
        task = Task { @MainActor in
            defer { busy = false }
            do { result = try await core.previewLibraryTag(resultId: id, name: tagDraft, remove: removeTag) }
            catch { if !Task.isCancelled { self.error = error.localizedDescription } }
        }
    }

    private func apply(_ response: LibraryAskResponse) {
        guard let id = response.result_id, !busy else { return }
        busy = true; error = nil
        task = Task { @MainActor in
            defer { busy = false }
            do {
                let applied = try await core.applyLibraryAction(resultId: id)
                feedback = applied.message; result?.action = nil; result?.books = applied.books
                NotificationCenter.default.post(name: .luminaLibraryRefresh, object: nil)
            } catch { if !Task.isCancelled { self.error = error.localizedDescription } }
        }
    }
}

private struct LibraryTagsView: View {
    @EnvironmentObject private var core: CoreClient
    @Environment(\.dismiss) private var dismiss
    var onSelect: (String) -> Void
    @State private var tags: [LibraryTag] = []
    @State private var draft = ""
    @State private var editing: LibraryTag?
    @State private var pendingDelete: LibraryTag?
    @State private var error: String?
    @State private var busy = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack { Text("书籍标签").font(.title2.bold()); Spacer(); Button("完成") { dismiss() } }
            HStack {
                TextField(editing == nil ? "新标签名称" : "修改标签名称", text: $draft).textFieldStyle(.roundedBorder)
                Button(editing == nil ? "创建" : "保存") { save() }.disabled(busy || draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                if editing != nil { Button("取消") { editing = nil; draft = "" } }
            }
            if let error { Text(error).foregroundStyle(.red).font(.caption) }
            if busy { ProgressView().controlSize(.small) }
            List(tags) { tag in
                HStack {
                    Button(tag.name) { dismiss(); onSelect(tag.name) }.buttonStyle(.link)
                    Text("\(tag.book_count) 本").font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Button("改名") { editing = tag; draft = tag.name }
                    Button("删除", role: .destructive) { pendingDelete = tag }
                }
            }.disabled(busy)
            Text("删除标签会从书籍上移除这个标签，书籍会保留。")
                .font(.caption).foregroundStyle(.secondary)
        }.padding(24).frame(width: 500, height: 420)
        .task { await load() }
        .confirmationDialog("删除标签？", isPresented: Binding(get: { pendingDelete != nil }, set: { if !$0 { pendingDelete = nil } })) {
            if let tag = pendingDelete {
                Button("删除「\(tag.name)」", role: .destructive) { remove(tag) }
            }
        }
    }

    @MainActor private func load() async {
        busy = true; defer { busy = false }
        do { tags = try await core.libraryTags() } catch { self.error = error.localizedDescription }
    }

    private func save() {
        busy = true; error = nil
        Task { @MainActor in
            defer { busy = false }
            do {
                tags = try await core.saveLibraryTag(name: draft, id: editing?.id); draft = ""; editing = nil
                NotificationCenter.default.post(name: .luminaLibraryRefresh, object: nil)
            }
            catch { self.error = error.localizedDescription }
        }
    }

    private func remove(_ tag: LibraryTag) {
        pendingDelete = nil; busy = true; error = nil
        Task { @MainActor in
            defer { busy = false }
            do {
                tags = try await core.deleteLibraryTag(id: tag.id)
                if editing?.id == tag.id { editing = nil; draft = "" }
                NotificationCenter.default.post(name: .luminaLibraryRefresh, object: nil)
            }
            catch { self.error = error.localizedDescription }
        }
    }
}
