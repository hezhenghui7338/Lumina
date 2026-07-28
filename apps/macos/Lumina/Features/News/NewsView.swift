import SwiftUI

struct NewsView: View {
    @EnvironmentObject private var core: CoreClient
    @State private var brief: NewsBrief?
    @State private var error: String?
    @State private var syncing = false

    var body: some View {
        Group {
            if let brief {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 12) {
                        HStack {
                            Text("今日简报")
                                .font(.title2.bold())
                            Spacer()
                            Text("\(brief.count) 篇")
                                .font(.caption)
                                .foregroundStyle(LuminaTheme.textSecondary)
                            Button(syncing ? "同步中…" : "同步 RSS") {
                                Task { await syncNews() }
                            }
                            .disabled(syncing)
                        }
                        .padding(.horizontal)

                        ForEach(brief.articles) { article in
                            NavigationLink(value: article.id) {
                                VStack(alignment: .leading, spacing: 6) {
                                    Text(article.title)
                                        .font(.headline)
                                        .foregroundStyle(LuminaTheme.textPrimary)
                                    if let excerpt = article.excerpt, !excerpt.isEmpty {
                                        Text(excerpt)
                                            .font(.subheadline)
                                            .foregroundStyle(LuminaTheme.textSecondary)
                                            .lineLimit(3)
                                    }
                                    if let published = article.published_at {
                                        Text(published)
                                            .font(.caption2)
                                            .foregroundStyle(.secondary)
                                    }
                                }
                                .luminaCard()
                            }
                            .buttonStyle(.plain)
                            .padding(.horizontal)
                        }
                    }
                    .padding(.vertical)
                }
            } else if let error {
                ContentUnavailableView("资讯加载失败", systemImage: "newspaper", description: Text(error))
            } else {
                ProgressView("加载资讯…")
            }
        }
        .background(LuminaTheme.background)
        .navigationTitle("资讯")
        .navigationDestination(for: String.self) { articleId in
            NewsArticleView(articleId: articleId)
        }
        .task { await loadBrief() }
    }

    private func loadBrief() async {
        do {
            brief = try await core.fetchNewsBrief()
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func syncNews() async {
        syncing = true
        defer { syncing = false }
        do {
            _ = try await core.syncNews()
            await loadBrief()
        } catch {
            self.error = error.localizedDescription
        }
    }
}
