import SwiftUI

struct SearchView: View {
    @EnvironmentObject private var core: CoreClient
    @Binding var isPresented: Bool
    @State private var query = ""
    @State private var results: [SearchHit] = []
    @State private var searching = false
    var onSelectBook: (String, Int?) -> Void

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Image(systemName: "magnifyingglass")
                    .foregroundStyle(LuminaTheme.textSecondary)
                TextField("跨书搜索…", text: $query)
                    .textFieldStyle(.plain)
                    .font(.title3)
                    .onSubmit { Task { await runSearch() } }
                if searching {
                    ProgressView().scaleEffect(0.7)
                }
                Button("关闭") { isPresented = false }
                    .keyboardShortcut(.escape, modifiers: [])
            }
            .padding()
            .background(LuminaTheme.surface)

            Divider()

            List(results) { hit in
                Button {
                    onSelectBook(hit.book_id, hit.segment_index)
                    isPresented = false
                } label: {
                    VStack(alignment: .leading, spacing: 4) {
                        HStack {
                            Text(hit.title)
                                .font(.headline)
                            Spacer()
                            Text(kindLabel(hit.kind))
                                .font(.caption2)
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(LuminaTheme.accentMuted)
                                .clipShape(Capsule())
                        }
                        if let snippet = hit.snippet {
                            Text(snippet)
                                .font(.caption)
                                .foregroundStyle(LuminaTheme.textSecondary)
                                .lineLimit(2)
                        }
                    }
                }
                .buttonStyle(.plain)
            }
            .listStyle(.plain)
        }
        .frame(width: 560, height: 420)
        .background(LuminaTheme.background)
        .onChange(of: query) { _, q in
            guard q.count >= 2 else { results = []; return }
            Task { await runSearch() }
        }
    }

    private func runSearch() async {
        let q = query.trimmingCharacters(in: .whitespaces)
        guard q.count >= 2 else { return }
        searching = true
        defer { searching = false }
        results = (try? await core.search(query: q)) ?? []
    }

    private func kindLabel(_ kind: String) -> String {
        switch kind {
        case "book": return "书籍"
        case "segment": return "段落"
        case "note": return "笔记"
        default: return kind
        }
    }
}
