import SwiftUI

struct NewsArticleView: View {
    let articleId: String
    var skim: NewsArticleCard? = nil

    @EnvironmentObject private var core: CoreClient
    @EnvironmentObject private var theme: ThemeManager
    @StateObject private var viewModel = NewsArticleViewModel()
    @State private var chatInput = ""

    var body: some View {
        VStack(spacing: 0) {
            articleContent
            Divider()
            chatPanel
        }
        .navigationTitle("精读")
        .toolbar {
            ToolbarItemGroup {
                Button {
                    theme.decreaseReadingFont()
                } label: {
                    Text("A−")
                        .font(.system(size: 12, weight: .medium))
                }
                .disabled(!theme.canDecreaseReadingFont)
                .help("减小字号")
                .accessibilityIdentifier("news.deepRead.fontDecrease")

                Button {
                    theme.increaseReadingFont()
                } label: {
                    Text("A+")
                        .font(.system(size: 14, weight: .semibold))
                }
                .disabled(!theme.canIncreaseReadingFont)
                .help("增大字号")
                .accessibilityIdentifier("news.deepRead.fontIncrease")

                if let url = articleURL {
                    Link("打开原文", destination: url)
                        .accessibilityIdentifier("news.deepRead.openOriginal")
                }
            }
        }
        .task(id: articleId) {
            await viewModel.load(articleId: articleId, service: core)
        }
        .onDisappear {
            viewModel.cancelAll()
        }
    }

    private var articleURL: URL? {
        NewsArticleViewModel.articleURL(article: viewModel.article, skim: skim)
    }

    private var articleContent: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: LuminaTheme.summarySectionSpacing) {
                Text(viewModel.article?.title ?? skim?.title ?? "…")
                    .font(.system(size: theme.scaled(22), weight: .semibold))
                    .foregroundStyle(LuminaTheme.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)

                if viewModel.isRefreshingSummary {
                    HStack(spacing: 10) {
                        ProgressView()
                            .controlSize(.small)
                        Text("生成速读卡…")
                            .font(.system(size: theme.scaled(12)))
                            .foregroundStyle(LuminaTheme.textSecondary)
                        Spacer()
                        Button("取消") {
                            viewModel.cancelLoad()
                        }
                        .accessibilityIdentifier("news.deepRead.cancelSummary")
                    }
                }

                summarySection

                if let body = viewModel.bodyText, !body.isEmpty {
                    Text(body)
                        .font(.system(size: theme.scaled(LuminaTheme.summaryBulletSize), weight: .regular))
                        .foregroundStyle(LuminaTheme.textPrimary)
                        .lineSpacing(theme.scaled(LuminaTheme.summaryBulletLineSpacing))
                        .fixedSize(horizontal: false, vertical: true)
                        .textSelection(.enabled)
                } else if !viewModel.isRefreshingSummary {
                    if let excerpt = viewModel.article?.excerpt ?? skim?.excerpt, !excerpt.isEmpty {
                        Text(excerpt)
                            .font(.system(size: theme.scaled(LuminaTheme.summaryBulletSize), weight: .regular))
                            .foregroundStyle(LuminaTheme.textSecondary)
                            .lineSpacing(theme.scaled(LuminaTheme.summaryBulletLineSpacing))
                            .fixedSize(horizontal: false, vertical: true)
                            .textSelection(.enabled)
                    }
                }

                if !viewModel.warnings.isEmpty {
                    Text(viewModel.warnings.joined(separator: "；"))
                        .font(.system(size: theme.scaled(11)))
                        .foregroundStyle(.orange)
                }
                if let err = viewModel.errorMessage, !err.isEmpty {
                    HStack(alignment: .top, spacing: 12) {
                        Text(err)
                            .font(.system(size: theme.scaled(11)))
                            .foregroundStyle(.red)
                        Button("重试生成") {
                            Task { await viewModel.retryLoad(service: core) }
                        }
                        .accessibilityIdentifier("news.deepRead.retrySummary")
                    }
                }
            }
            .padding(LuminaTheme.summaryPadding)
            .readingColumn()
            .padding(.horizontal, 28)
            .padding(.vertical, 16)
        }
        .frame(maxHeight: .infinity)
        .background(LuminaTheme.background)
    }

    @ViewBuilder
    private var summarySection: some View {
        if let md = viewModel.summaryMarkdown, !md.isEmpty {
            NewsSummarySection(
                markdown: md,
                scale: theme.readingFontScale,
                onFollowUp: { question in
                    Task { await viewModel.sendChat(question, service: core) }
                }
            )
        } else if let skim {
            NewsSkimSummaryBlock(article: skim, scale: theme.readingFontScale)
        }
    }

    private var chatPanel: some View {
        VStack(spacing: 8) {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 8) {
                        ForEach(viewModel.messages) { msg in
                            VStack(alignment: .leading, spacing: 4) {
                                HStack {
                                    Text(msg.role == "user" ? "你" : "深聊")
                                        .font(.caption.bold())
                                    if msg.role == "assistant", msg.content.isEmpty, viewModel.isSending {
                                        ProgressView()
                                            .controlSize(.small)
                                        Text("正在响应…")
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
                                    }
                                    Spacer()
                                }
                                if !msg.content.isEmpty {
                                    Text(msg.content)
                                }
                                if let attribution = ChatMetricsFormatter.attribution(for: msg) {
                                    Text(attribution)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                            }
                            .padding(8)
                            .background(msg.role == "user" ? Color.blue.opacity(0.08) : Color.gray.opacity(0.08))
                            .clipShape(RoundedRectangle(cornerRadius: 8))
                            .id(msg.id)
                        }
                    }
                    .padding(.horizontal)
                }
                .frame(height: 220)
                .onChange(of: viewModel.messages.count) { _, _ in
                    scrollChatToBottom(proxy: proxy)
                }
                .onChange(of: viewModel.messages.last?.content) { _, _ in
                    scrollChatToBottom(proxy: proxy)
                }
            }

            HStack {
                TextField("提问…", text: $chatInput)
                    .textFieldStyle(.roundedBorder)
                    .disabled(viewModel.isSending)
                    .onSubmit { submitChat() }
                Button("发送") { submitChat() }
                    .disabled(
                        chatInput.trimmingCharacters(in: .whitespaces).isEmpty || viewModel.isSending
                    )
                    .accessibilityIdentifier("news.deepRead.chatSend")
            }
            .padding(.horizontal)
            .padding(.bottom, 8)
        }
    }

    private func submitChat() {
        let text = chatInput.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !viewModel.isSending else { return }
        chatInput = ""
        Task { await viewModel.sendChat(text, service: core) }
    }

    private func scrollChatToBottom(proxy: ScrollViewProxy) {
        guard let last = viewModel.messages.last else { return }
        withAnimation(.easeOut(duration: 0.2)) {
            proxy.scrollTo(last.id, anchor: .bottom)
        }
    }
}

/// News deep-read summary with tappable follow-up chips parsed from markdown.
struct NewsSummarySection: View {
    let markdown: String
    var scale: Double = 1.0
    var onFollowUp: ((String) -> Void)?

    var body: some View {
        NewsStructuredSummaryView(
            markdown: markdown,
            scale: scale,
            onFollowUp: onFollowUp,
            showsBackground: true
        )
    }
}

/// Compact skim used as pre-LLM summary card in deep-read view.
struct NewsSkimSummaryBlock: View {
    let article: NewsArticleCard
    var scale: Double = 1.0

    private func scaled(_ base: CGFloat) -> CGFloat {
        base * CGFloat(scale)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: LuminaTheme.summarySectionSpacing * 0.6) {
            Text("速读")
                .font(.system(size: scaled(LuminaTheme.summaryLabelSize), weight: .semibold))
                .foregroundStyle(LuminaTheme.textSecondary)
                .tracking(0.6)

            if let one = article.one_liner ?? article.excerpt, !one.isEmpty {
                Text(one)
                    .font(.system(size: scaled(LuminaTheme.summaryLeadSize), weight: .regular))
                    .foregroundStyle(LuminaTheme.textPrimary)
                    .lineSpacing(scaled(LuminaTheme.summaryLeadLineSpacing))
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }

            if !article.viewpoints.isEmpty {
                VStack(alignment: .leading, spacing: LuminaTheme.summaryBulletItemSpacing) {
                    ForEach(Array(article.viewpoints.prefix(5).enumerated()), id: \.offset) { _, vp in
                        NewsSkimBulletRow(text: vp, italic: false, scale: scale)
                    }
                }
            }
        }
        .padding(LuminaTheme.summaryPadding)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: LuminaTheme.summaryCornerRadius)
                .fill(LuminaTheme.accentMuted.opacity(0.45))
        )
    }
}

protocol NewsArticleServing {
    func fetchNewsArticle(id: String) async throws -> NewsArticleDetail
    func readNewsArticle(id: String, forceRefetch: Bool, skimOnly: Bool) async throws -> NewsReadResult
    func newsChatStream(
        articleId: String,
        message: String,
        quote: String?,
        onToken: @escaping (String) -> Void
    ) async throws -> ChatResponse
}

extension NewsArticleServing {
    func readNewsArticle(id: String, forceRefetch: Bool = false) async throws -> NewsReadResult {
        try await readNewsArticle(id: id, forceRefetch: forceRefetch, skimOnly: false)
    }
}

extension CoreClient: NewsArticleServing {}

struct NewsReadTimeoutError: LocalizedError {
    var errorDescription: String? { "生成速读卡超时，请重试" }
}

@MainActor
final class NewsArticleViewModel: ObservableObject {
    @Published var article: NewsArticleDetail?
    @Published var summaryMarkdown: String?
    @Published var bodyText: String?
    @Published var warnings: [String] = []
    @Published var errorMessage: String?
    @Published var isRefreshingSummary = false
    @Published var isSending = false
    @Published var messages: [ChatMessage] = []

    var readTimeoutSeconds: TimeInterval = 180

    private var articleId = ""
    private var loadTask: Task<Void, Never>?
    private var chatTask: Task<Void, Never>?

    static func articleURL(article: NewsArticleDetail?, skim: NewsArticleCard?) -> URL? {
        if let raw = article?.url ?? skim?.url {
            return URL(string: raw)
        }
        return nil
    }

    func cancelLoad() {
        loadTask?.cancel()
        loadTask = nil
        isRefreshingSummary = false
    }

    func cancelChat() {
        chatTask?.cancel()
        chatTask = nil
        isSending = false
    }

    func cancelAll() {
        cancelLoad()
        cancelChat()
    }

    func load(articleId: String, service: NewsArticleServing, forceRead: Bool = false) async {
        cancelLoad()
        self.articleId = articleId
        errorMessage = nil

        let task = Task {
            await performLoad(articleId: articleId, service: service, forceRead: forceRead)
        }
        loadTask = task
        await task.value
        if !task.isCancelled {
            loadTask = nil
        }
    }

    func retryLoad(service: NewsArticleServing) async {
        await load(articleId: articleId, service: service, forceRead: true)
    }

    private func performLoad(articleId: String, service: NewsArticleServing, forceRead: Bool) async {
        do {
            let detail = try await service.fetchNewsArticle(id: articleId)
            try Task.checkCancellation()
            article = detail

            if !forceRead, Self.hasCachedSummary(detail) {
                summaryMarkdown = detail.summary_markdown
                return
            }

            isRefreshingSummary = true
            defer { isRefreshingSummary = false }

            let result = try await Self.withTimeout(seconds: readTimeoutSeconds) {
                try Task.checkCancellation()
                return try await service.readNewsArticle(id: articleId, forceRefetch: forceRead)
            }
            try Task.checkCancellation()

            article = result.article
            summaryMarkdown = result.summary_markdown
            bodyText = result.body_text
            warnings = result.warnings
            errorMessage = result.error.isEmpty ? nil : result.error
        } catch is CancellationError {
            return
        } catch let error as URLError where error.code == .cancelled {
            return
        } catch is NewsReadTimeoutError {
            errorMessage = NewsReadTimeoutError().errorDescription
            if summaryMarkdown == nil {
                summaryMarkdown = article?.summary_markdown
            }
        } catch {
            errorMessage = error.localizedDescription
            if summaryMarkdown == nil {
                summaryMarkdown = article?.summary_markdown
            }
        }
    }

    func sendChat(_ text: String, quote: String? = nil, service: NewsArticleServing) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !isSending else { return }

        chatTask?.cancel()
        let task = Task { await performSendChat(trimmed, quote: quote, service: service) }
        chatTask = task
        await task.value
        if chatTask == task {
            chatTask = nil
        }
    }

    private func performSendChat(
        _ text: String,
        quote: String?,
        service: NewsArticleServing
    ) async {
        isSending = true
        defer { isSending = false }

        messages.append(ChatMessage(role: "user", content: text))
        messages.append(ChatMessage(role: "assistant", content: ""))
        let idx = messages.count - 1

        do {
            let resp = try await service.newsChatStream(articleId: articleId, message: text, quote: quote) { token in
                Task { @MainActor in
                    guard idx < self.messages.count else { return }
                    var msg = self.messages[idx]
                    msg.content += token
                    self.messages[idx] = msg
                }
            }
            try Task.checkCancellation()
            guard idx < messages.count else { return }
            var msg = messages[idx]
            msg.content = resp.answer
            msg.applyMetrics(from: resp)
            messages[idx] = msg
        } catch is CancellationError {
            if idx < messages.count, messages[idx].content.isEmpty {
                var msg = messages[idx]
                msg.content = "已取消"
                messages[idx] = msg
            }
        } catch let error as URLError where error.code == .cancelled {
            if idx < messages.count, messages[idx].content.isEmpty {
                var msg = messages[idx]
                msg.content = "已取消"
                messages[idx] = msg
            }
        } catch {
            guard idx < messages.count else { return }
            var msg = messages[idx]
            msg.content = "深聊失败：\(error.localizedDescription)"
            messages[idx] = msg
        }
    }

    private static func hasCachedSummary(_ detail: NewsArticleDetail) -> Bool {
        detail.summary_status == "ready"
            && (detail.summary_markdown?.isEmpty == false)
    }

    private static func withTimeout<T>(
        seconds: TimeInterval,
        operation: @escaping () async throws -> T
    ) async throws -> T {
        try await withThrowingTaskGroup(of: T.self) { group in
            group.addTask {
                try await operation()
            }
            group.addTask {
                try await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
                throw NewsReadTimeoutError()
            }
            guard let result = try await group.next() else {
                throw NewsReadTimeoutError()
            }
            group.cancelAll()
            return result
        }
    }
}

struct NewsArticleDetail: Codable {
    let id: String
    let title: String
    let excerpt: String?
    let one_liner: String?
    let url: String
    let author: String?
    let published_at: String?
    let summary_markdown: String?
    let summary_status: String?
    let score_hint: Double?
}

struct NewsReadResult: Codable {
    let article: NewsArticleDetail
    let summary_markdown: String
    let warnings: [String]
    let error: String
    let body_complete: Bool
    let body_text: String?

    enum CodingKeys: String, CodingKey {
        case article, summary_markdown, warnings, error, body_complete, body_text
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        article = try c.decode(NewsArticleDetail.self, forKey: .article)
        summary_markdown = try c.decode(String.self, forKey: .summary_markdown)
        warnings = try c.decodeIfPresent([String].self, forKey: .warnings) ?? []
        error = try c.decodeIfPresent(String.self, forKey: .error) ?? ""
        body_complete = try c.decodeIfPresent(Bool.self, forKey: .body_complete) ?? true
        body_text = try c.decodeIfPresent(String.self, forKey: .body_text)
    }
}
