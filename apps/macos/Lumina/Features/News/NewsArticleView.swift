import SwiftUI

struct NewsArticleView: View {
    let articleId: String
    @EnvironmentObject private var core: CoreClient
    @StateObject private var viewModel = NewsArticleViewModel()
    @State private var chatInput = ""

    var body: some View {
        HStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    if let article = viewModel.article {
                        Text(article.title)
                            .font(.title2.bold())
                        if let excerpt = article.excerpt, !excerpt.isEmpty {
                            Text(excerpt)
                                .font(.body)
                                .foregroundStyle(LuminaTheme.textSecondary)
                        }
                        if let url = URL(string: article.url) {
                            Link("阅读原文", destination: url)
                        }
                    } else {
                        ProgressView("加载文章…")
                    }
                }
                .padding()
                .frame(maxWidth: .infinity, alignment: .leading)
            }

            Divider()

            VStack(spacing: 0) {
                chatMessages
                Divider()
                chatInputBar
            }
            .frame(width: 360)
        }
        .navigationTitle("精读")
        .task { await viewModel.load(articleId: articleId, core: core) }
    }

    private var chatMessages: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 8) {
                ForEach(viewModel.messages) { msg in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(msg.role == "user" ? "你" : "深聊")
                            .font(.caption.bold())
                        Text(msg.content)
                    }
                    .padding(8)
                    .background(msg.role == "user" ? Color.blue.opacity(0.08) : Color.gray.opacity(0.08))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                }
            }
            .padding()
        }
    }

    private var chatInputBar: some View {
        HStack {
            TextField("提问…", text: $chatInput)
                .textFieldStyle(.roundedBorder)
            Button("发送") {
                let text = chatInput
                chatInput = ""
                Task { await viewModel.sendChat(text, core: core) }
            }
            .disabled(chatInput.trimmingCharacters(in: .whitespaces).isEmpty)
        }
        .padding()
    }
}

@MainActor
final class NewsArticleViewModel: ObservableObject {
    @Published var article: NewsArticleDetail?
    @Published var messages: [ChatMessage] = []
    private var articleId = ""

    func load(articleId: String, core: CoreClient) async {
        self.articleId = articleId
        article = try? await core.fetchNewsArticle(id: articleId)
    }

    func sendChat(_ text: String, core: CoreClient) async {
        messages.append(ChatMessage(role: "user", content: text))
        var assistant = ChatMessage(role: "assistant", content: "")
        messages.append(assistant)
        let idx = messages.count - 1

        do {
            let resp = try await core.newsChatStream(articleId: articleId, message: text) { token in
                Task { @MainActor in
                    self.messages[idx].content += token
                }
            }
            messages[idx].content = resp.answer
        } catch {
            messages[idx].content = "深聊失败：\(error.localizedDescription)"
        }
    }
}

struct NewsArticleDetail: Codable {
    let id: String
    let title: String
    let excerpt: String?
    let url: String
    let author: String?
    let published_at: String?
}
