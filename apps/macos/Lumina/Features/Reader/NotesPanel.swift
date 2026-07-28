import SwiftUI

struct NotesPanel: View {
    let bookId: String
    let segmentId: String?
    @EnvironmentObject private var core: CoreClient
    @State private var notes: [NoteRow] = []
    @State private var draft = ""
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("笔记").font(.headline)
                Spacer()
                Button("新建") { Task { await createNote() } }
                    .disabled(draft.trimmingCharacters(in: .whitespaces).isEmpty)
            }

            TextField("写笔记…", text: $draft, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(2...4)

            if notes.isEmpty {
                Text("暂无笔记").font(.caption).foregroundStyle(.secondary)
            } else {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 8) {
                        ForEach(notes) { note in
                            VStack(alignment: .leading, spacing: 4) {
                                if let quote = note.quote, !quote.isEmpty {
                                    Text("「\(quote)」")
                                        .font(.caption)
                                        .foregroundStyle(LuminaTheme.accent)
                                }
                                Text(note.content)
                                    .font(.subheadline)
                                Text(note.type)
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                            }
                            .luminaCard()
                        }
                    }
                }
            }
        }
        .padding(10)
        .frame(width: 220)
        .background(LuminaTheme.surface.opacity(0.6))
        .task(id: bookId) { await reload() }
        .alert("笔记错误", isPresented: .constant(error != nil)) {
            Button("好") { error = nil }
        } message: {
            Text(error ?? "")
        }
    }

    func saveFromChat(_ content: String, quote: String? = nil) async {
        draft = content
        await createNote(quote: quote, type: "ai")
    }

    private func reload() async {
        notes = (try? await core.listNotes(bookId: bookId)) ?? []
    }

    private func createNote(quote: String? = nil, type: String = "manual") async {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
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
        } catch {
            self.error = error.localizedDescription
        }
    }
}

struct NoteRow: Codable, Identifiable, Hashable {
    let id: String
    let book_id: String
    let segment_id: String?
    let quote: String?
    let content: String
    let type: String
    let created_at: String
}
