import SwiftUI

private let articleSwitchDuration: TimeInterval = 0.05
private let newsBriefLimitOptions = [5, 10, 15, 20, 30, 50]

struct NewsView: View {
    @EnvironmentObject private var core: CoreClient
    @EnvironmentObject private var sidecar: SidecarManager
    @EnvironmentObject private var theme: ThemeManager
    @AppStorage("lumina.news.briefLimit") private var briefLimit = 25
    @AppStorage("lumina.news.sourceFilter") private var sourceFilter = "all"
    @State private var brief: NewsBrief?
    @State private var sources: [NewsSource] = []
    @State private var articlesById: [String: NewsArticleCard] = [:]
    @State private var selectedId: String?
    @State private var error: String?
    @State private var syncing = false
    @State private var showSourceManager = false
    @State private var path = NavigationPath()
    @StateObject private var skimViewModel = NewsSkimViewModel()

    private var filteredArticles: [NewsArticleCard] {
        guard let brief else { return [] }
        guard sourceFilter != "all" else { return brief.articles }
        return brief.articles.filter { $0.source_id == sourceFilter }
    }

    private var selectedArticle: NewsArticleCard? {
        guard let selectedId else { return nil }
        return articlesById[selectedId]
    }

    var body: some View {
        Group {
            if let brief {
                NavigationSplitView {
                    articleSidebar()
                } detail: {
                    NavigationStack(path: $path) {
                        skimPane
                            .navigationDestination(for: String.self) { articleId in
                                NewsArticleView(articleId: articleId, skim: articlesById[articleId])
                            }
                    }
                }
            } else if let error {
                ContentUnavailableView {
                    Label("资讯加载失败", systemImage: "newspaper")
                } description: {
                    Text(error)
                } actions: {
                    Button("重试") {
                        Task { await loadBrief() }
                    }
                }
            } else {
                ProgressView("加载资讯…")
            }
        }
        .background(LuminaTheme.background)
        .navigationTitle("今日简报")
        .toolbar {
            ToolbarItemGroup {
                sourceFilterPicker

                briefLimitMenu

                if let brief {
                    Text("\(filteredArticles.count)/\(brief.count) 篇")
                        .font(.caption)
                        .foregroundStyle(LuminaTheme.textSecondary)
                }
                Button {
                    theme.decreaseReadingFont()
                } label: {
                    Text("A−")
                        .font(.system(size: 12, weight: .medium))
                }
                .disabled(!theme.canDecreaseReadingFont)
                .help("减小字号")

                Button {
                    theme.increaseReadingFont()
                } label: {
                    Text("A+")
                        .font(.system(size: 14, weight: .semibold))
                }
                .disabled(!theme.canIncreaseReadingFont)
                .help("增大字号")

                Button(syncing ? "同步中…" : "同步 RSS") {
                    Task { await syncNews() }
                }
                .disabled(syncing)

                Button("管理信源") {
                    showSourceManager = true
                }
                .help("添加或删除 RSS 订阅源")

                if selectedArticle != nil {
                    Button("精读") {
                        if let id = selectedId {
                            path.append(id)
                        }
                    }
                    .keyboardShortcut(.defaultAction)
                }
            }
        }
        .task(id: sidecar.isRunning) {
            await loadSources()
            await loadBrief()
        }
        .onChange(of: briefLimit) { _, _ in
            Task { await loadBrief() }
        }
        .sheet(isPresented: $showSourceManager) {
            NavigationStack {
                NewsSourcesSettingsView(showsDismissButton: true) {
                    Task {
                        await loadSources()
                        await loadBrief()
                    }
                }
            }
            .environmentObject(core)
        }
    }

    @ViewBuilder
    private var sourceFilterPicker: some View {
        Picker("信源", selection: $sourceFilter) {
            Text("全部").tag("all")
            ForEach(sources) { source in
                Text(sourceDisplayTitle(source)).tag(source.id)
            }
        }
        .pickerStyle(.menu)
        .labelsHidden()
        .frame(maxWidth: 140)
        .help("按 RSS 信源筛选")
    }

    private var briefLimitMenu: some View {
        Menu {
            ForEach(newsBriefLimitOptions, id: \.self) { limit in
                Button {
                    briefLimit = limit
                } label: {
                    if limit == briefLimit {
                        Label("\(limit) 篇", systemImage: "checkmark")
                    } else {
                        Text("\(limit) 篇")
                    }
                }
            }
        } label: {
            Text("\(briefLimit) 篇")
                .font(.caption)
        }
        .help("简报篇数上限")
    }

    private func sourceDisplayTitle(_ source: NewsSource) -> String {
        let title = source.title?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return title.isEmpty ? source.url : title
    }

    private func articleSidebar() -> some View {
        Group {
            if filteredArticles.isEmpty {
                ContentUnavailableView {
                    Label("该信源暂无文章", systemImage: "newspaper")
                } description: {
                    Text("试试切换「全部」或同步 RSS。")
                } actions: {
                    Button("显示全部") { sourceFilter = "all" }
                }
            } else {
                List(selection: $selectedId) {
                    ForEach(filteredArticles.indices, id: \.self) { index in
                        let article = filteredArticles[index]
                        HStack(alignment: .top, spacing: 10) {
                            Text("\(index + 1).")
                                .font(.system(size: 12, weight: .medium).monospacedDigit())
                                .foregroundStyle(LuminaTheme.textSecondary)
                                .frame(width: 28, alignment: .trailing)
                            VStack(alignment: .leading, spacing: 5) {
                                Text(article.title)
                                    .font(.system(size: 14.5, weight: .medium))
                                    .foregroundStyle(LuminaTheme.textPrimary)
                                    .lineLimit(2)
                                    .fixedSize(horizontal: false, vertical: true)
                                HStack(spacing: 6) {
                                    if let source = displaySource(article) {
                                        Text(source)
                                            .lineLimit(1)
                                    }
                                    if let published = article.published_at {
                                        Text(published.prefix(10))
                                    }
                                }
                                .font(.system(size: 11))
                                .foregroundStyle(LuminaTheme.textSecondary)
                            }
                        }
                        .padding(.vertical, 4)
                        .tag(article.id)
                        .listRowInsets(EdgeInsets(top: 8, leading: 12, bottom: 8, trailing: 12))
                        .background(
                            DoubleClickHandler {
                                selectedId = article.id
                                path.append(article.id)
                            }
                        )
                    }
                }
                .listStyle(.sidebar)
            }
        }
        .navigationSplitViewColumnWidth(min: 260, ideal: 300, max: 340)
        .onAppear {
            ensureValidSelection()
        }
        .onChange(of: filteredArticles.map(\.id)) { _, _ in
            ensureValidSelection()
        }
    }

    private func ensureValidSelection() {
        let ids = filteredArticles.map(\.id)
        if let selectedId, ids.contains(selectedId) { return }
        self.selectedId = ids.first
    }

    @ViewBuilder
    private var skimPane: some View {
        if let article = selectedArticle {
            NewsSkimPane(
                article: article,
                scale: theme.readingFontScale,
                viewModel: skimViewModel,
                onRetry: {
                    Task {
                        await skimViewModel.retryLoad(article: article, service: core)
                    }
                }
            )
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(LuminaTheme.background)
            .task(id: article.id) {
                await skimViewModel.load(article: article, service: core)
            }
            .onDisappear {
                skimViewModel.cancelLoad()
            }
        } else if filteredArticles.isEmpty, brief != nil {
            ContentUnavailableView("该信源暂无文章", systemImage: "newspaper", description: Text("切换信源或同步 RSS"))
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else {
            ContentUnavailableView("选择一篇资讯", systemImage: "newspaper", description: Text("左侧列表点选后可速读"))
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    private func displaySource(_ article: NewsArticleCard) -> String? {
        if let s = article.source_title, !s.isEmpty { return s }
        if let s = article.meta["source"], !s.isEmpty { return s }
        if let s = article.source, !s.isEmpty { return s }
        return nil
    }

    private func loadSources() async {
        guard await sidecar.waitUntilReady() else { return }
        do {
            sources = try await core.fetchNewsSources()
            if sourceFilter != "all", !sources.contains(where: { $0.id == sourceFilter }) {
                sourceFilter = "all"
            }
        } catch {
            // Non-fatal: filter falls back to loaded brief articles only.
        }
    }

    private func loadBrief() async {
        error = nil
        guard await sidecar.waitUntilReady() else {
            self.error = sidecar.launchError ?? "无法连接到 AI 引擎，请重试。"
            return
        }
        let clampedLimit = min(max(briefLimit, newsBriefLimitOptions.first ?? 5), newsBriefLimitOptions.last ?? 50)
        if clampedLimit != briefLimit {
            briefLimit = clampedLimit
        }
        do {
            let loaded = try await core.fetchNewsBrief(limit: clampedLimit)
            brief = loaded
            articlesById = Dictionary(uniqueKeysWithValues: loaded.articles.map { ($0.id, $0) })
            ensureValidSelection()
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func syncNews() async {
        syncing = true
        defer { syncing = false }
        do {
            _ = try await core.syncNews()
            await loadSources()
            await loadBrief()
        } catch {
            self.error = error.localizedDescription
        }
    }
}

// MARK: - Skim pane

enum NewsSkimLoadState: Equatable {
    case idle
    case loading
    case ready
    case error
}

protocol NewsSkimServing: NewsArticleServing {}

extension CoreClient: NewsSkimServing {}

@MainActor
final class NewsSkimViewModel: ObservableObject {
    @Published var summaryMarkdown: String?
    @Published var loadState: NewsSkimLoadState = .idle
    @Published var errorMessage: String?

    var readTimeoutSeconds: TimeInterval = 180

    private var loadTask: Task<Void, Never>?
    private var articleId = ""

    func cancelLoad() {
        loadTask?.cancel()
        loadTask = nil
        if loadState == .loading {
            loadState = .idle
        }
    }

    func load(article: NewsArticleCard, service: NewsSkimServing) async {
        cancelLoad()
        articleId = article.id
        summaryMarkdown = nil
        errorMessage = nil

        guard article.needsLLMSkim else {
            loadState = .idle
            return
        }

        let task = Task {
            await performLoad(article: article, service: service, forceRead: false)
        }
        loadTask = task
        await task.value
        if !task.isCancelled {
            loadTask = nil
        }
    }

    func retryLoad(article: NewsArticleCard, service: NewsSkimServing) async {
        cancelLoad()
        articleId = article.id
        errorMessage = nil
        summaryMarkdown = nil

        let task = Task {
            await performLoad(article: article, service: service, forceRead: true)
        }
        loadTask = task
        await task.value
        if !task.isCancelled {
            loadTask = nil
        }
    }

    private func performLoad(
        article: NewsArticleCard,
        service: NewsSkimServing,
        forceRead: Bool
    ) async {
        loadState = .loading
        do {
            let detail = try await service.fetchNewsArticle(id: article.id)
            try Task.checkCancellation()

            if !forceRead, Self.hasCachedSummary(detail) {
                summaryMarkdown = detail.summary_markdown
                loadState = .ready
                return
            }

            let result = try await Self.withTimeout(seconds: readTimeoutSeconds) {
                try Task.checkCancellation()
                return try await service.readNewsArticle(
                    id: article.id,
                    forceRefetch: forceRead,
                    skimOnly: true
                )
            }
            try Task.checkCancellation()

            summaryMarkdown = result.summary_markdown
            loadState = .ready
            errorMessage = result.error.isEmpty ? nil : result.error
        } catch is CancellationError {
            return
        } catch let error as URLError where error.code == .cancelled {
            return
        } catch is NewsReadTimeoutError {
            loadState = .error
            errorMessage = NewsReadTimeoutError().errorDescription
        } catch {
            loadState = .error
            errorMessage = error.localizedDescription
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

struct NewsSkimPane: View {
    let article: NewsArticleCard
    let scale: Double
    @ObservedObject var viewModel: NewsSkimViewModel
    var onRetry: () -> Void

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: LuminaTheme.summarySectionSpacing) {
                    skimContent
                }
                .padding(.horizontal, 28)
                .padding(.vertical, 24)
                .frame(maxWidth: .infinity, alignment: .leading)
                .id(article.id)
            }
            .onChange(of: article.id) { _, id in
                DispatchQueue.main.async {
                    proxy.scrollTo(id, anchor: .top)
                }
            }
        }
        .animation(.easeInOut(duration: articleSwitchDuration), value: article.id)
        .animation(.easeInOut(duration: 0.2), value: viewModel.loadState)
    }

    @ViewBuilder
    private var skimContent: some View {
        if article.needsLLMSkim,
           viewModel.loadState == .ready,
           let markdown = viewModel.summaryMarkdown,
           !markdown.isEmpty {
            llmSkimContent(markdown: markdown)
        } else if article.needsLLMSkim, viewModel.loadState == .loading {
            NewsSkimCard(article: article, scale: scale, includeFooter: false)
            SummarySkimSkeleton(scale: scale)
            skimLoadingRow
            NewsSkimFooter(article: article, scale: scale)
        } else if article.needsLLMSkim, viewModel.loadState == .error {
            NewsSkimCard(article: article, scale: scale, includeFooter: false)
            skimErrorRow
            NewsSkimFooter(article: article, scale: scale)
        } else {
            NewsSkimCard(article: article, scale: scale)
        }
    }

    @ViewBuilder
    private func llmSkimContent(markdown: String) -> some View {
        Text("速读")
            .font(.system(size: scaled(LuminaTheme.summaryLabelSize), weight: .semibold))
            .foregroundStyle(LuminaTheme.textSecondary)
            .tracking(0.6)

        Text(article.title)
            .font(.system(size: scaled(22), weight: .semibold))
            .foregroundStyle(LuminaTheme.textPrimary)
            .fixedSize(horizontal: false, vertical: true)
            .textSelection(.enabled)

        NewsStructuredSummaryView(
            markdown: markdown,
            scale: scale,
            onFollowUp: nil,
            showsBackground: true
        )

        NewsSkimFooter(article: article, scale: scale)
    }

    private var skimLoadingRow: some View {
        HStack(spacing: 10) {
            ProgressView()
                .controlSize(.small)
            Text("生成结构化速读…")
                .font(.system(size: scaled(12)))
                .foregroundStyle(LuminaTheme.textSecondary)
            Spacer()
        }
    }

    private var skimErrorRow: some View {
        HStack(alignment: .top, spacing: 12) {
            Text(viewModel.errorMessage ?? "生成失败")
                .font(.system(size: scaled(11)))
                .foregroundStyle(.red)
            Button("重试") {
                onRetry()
            }
        }
    }

    private func scaled(_ base: CGFloat) -> CGFloat {
        base * CGFloat(scale)
    }
}

// MARK: - Skim card

struct NewsSkimCard: View {
    let article: NewsArticleCard
    var scale: Double = 1.0
    var includeFooter: Bool = true

    private func scaled(_ base: CGFloat) -> CGFloat {
        base * CGFloat(scale)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: LuminaTheme.summarySectionSpacing) {
            Text("速读")
                .font(.system(size: scaled(LuminaTheme.summaryLabelSize), weight: .semibold))
                .foregroundStyle(LuminaTheme.textSecondary)
                .tracking(0.6)

            Text(article.title)
                .font(.system(size: scaled(22), weight: .semibold))
                .foregroundStyle(LuminaTheme.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)

            if let one = article.one_liner ?? article.excerpt, !one.isEmpty {
                Text(one)
                    .font(.system(size: scaled(LuminaTheme.summaryLeadSize), weight: .regular))
                    .foregroundStyle(LuminaTheme.textPrimary)
                    .lineSpacing(scaled(LuminaTheme.summaryLeadLineSpacing))
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }

            if let detail = article.detail, !detail.isEmpty {
                skimSection("详细摘要") {
                    Text(detail)
                        .font(.system(size: scaled(LuminaTheme.summaryBulletSize), weight: .regular))
                        .foregroundStyle(LuminaTheme.textSecondary)
                        .lineSpacing(scaled(LuminaTheme.summaryBulletLineSpacing))
                        .fixedSize(horizontal: false, vertical: true)
                        .textSelection(.enabled)
                }
            }

            if !article.viewpoints.isEmpty {
                skimSection("主要观点") {
                    VStack(alignment: .leading, spacing: LuminaTheme.summaryBulletItemSpacing) {
                        ForEach(Array(article.viewpoints.enumerated()), id: \.offset) { _, vp in
                            NewsSkimBulletRow(text: vp, italic: false, scale: scale)
                        }
                    }
                }
            }

            if !article.quotes.isEmpty {
                skimSection("金句") {
                    VStack(alignment: .leading, spacing: LuminaTheme.summaryBulletItemSpacing) {
                        ForEach(Array(article.quotes.enumerated()), id: \.offset) { _, q in
                            NewsSkimBulletRow(text: q, italic: true, scale: scale)
                        }
                    }
                }
            }

            if includeFooter {
                NewsSkimFooter(article: article, scale: scale)
            }
        }
        .padding(LuminaTheme.summaryPadding)
        .readingColumn()
        .background(
            RoundedRectangle(cornerRadius: LuminaTheme.summaryCornerRadius)
                .fill(LuminaTheme.accentMuted.opacity(0.45))
        )
    }

    private func skimSection(_ title: String, @ViewBuilder content: () -> some View) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title)
                .font(.system(size: scaled(LuminaTheme.summaryLabelSize), weight: .semibold))
                .foregroundStyle(LuminaTheme.textSecondary)
                .tracking(0.6)
            content()
        }
    }
}

struct NewsSkimFooter: View {
    let article: NewsArticleCard
    var scale: Double = 1.0

    private func scaled(_ base: CGFloat) -> CGFloat {
        base * CGFloat(scale)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Divider()
                .background(LuminaTheme.border)

            VStack(alignment: .leading, spacing: 8) {
                if !article.reasons.isEmpty {
                    Text("入选：\(article.reasons.prefix(3).joined(separator: " · "))")
                }
                let bits = metaBits
                if !bits.isEmpty {
                    Text(bits.joined(separator: " · "))
                }
            }
            .font(.system(size: scaled(11)))
            .foregroundStyle(LuminaTheme.textSecondary)

            if let url = URL(string: article.url) {
                Link("打开原文", destination: url)
                    .font(.system(size: scaled(LuminaTheme.summaryBulletSize), weight: .medium))
            }
        }
    }

    private var metaBits: [String] {
        var bits: [String] = []
        if let published = article.published_at, published.count >= 10 {
            bits.append(String(published.prefix(10)))
        }
        if let score = article.meta["ai_score"] ?? article.score_hint.map({ String(format: "%.0f", $0) }) {
            bits.append("AI \(score)")
        }
        if let mins = article.meta["read_mins"] {
            bits.append("\(mins) 分钟")
        }
        if let source = article.source_title ?? article.meta["source"] ?? article.source {
            bits.append(source)
        }
        return bits
    }
}

struct NewsSkimBulletRow: View {
    let text: String
    var italic: Bool = false
    var scale: Double = 1.0

    private func scaled(_ base: CGFloat) -> CGFloat {
        base * CGFloat(scale)
    }

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            RoundedRectangle(cornerRadius: 1)
                .fill(LuminaTheme.accent.opacity(0.55))
                .frame(width: 2)
                .padding(.top, 4)
                .padding(.bottom, 2)

            Text(text)
                .font(bulletFont)
                .foregroundStyle(LuminaTheme.textPrimary)
                .lineSpacing(scaled(LuminaTheme.summaryBulletLineSpacing))
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var bulletFont: Font {
        let base = Font.system(size: scaled(LuminaTheme.summaryBulletSize), weight: .regular)
        return italic ? base.italic() : base
    }
}
