import XCTest
@testable import Lumina

@MainActor
final class NewsArticleViewModelTests: XCTestCase {
    private func makeDetail(
        id: String = "art1",
        summaryStatus: String? = nil,
        summaryMarkdown: String? = nil
    ) -> NewsArticleDetail {
        NewsArticleDetail(
            id: id,
            title: "Test Article",
            excerpt: "Brief excerpt",
            one_liner: "One liner",
            url: "https://example.com/\(id)",
            author: nil,
            published_at: "2024-01-01",
            summary_markdown: summaryMarkdown,
            summary_status: summaryStatus,
            score_hint: 90
        )
    }

    private func makeReadResult(summary: String = "## 总结\nGenerated.") throws -> NewsReadResult {
        let json = """
        {
          "article": {
            "id": "art1",
            "title": "Test Article",
            "excerpt": "Brief excerpt",
            "one_liner": "One liner",
            "url": "https://example.com/art1",
            "author": null,
            "published_at": "2024-01-01",
            "summary_markdown": "\(summary.replacingOccurrences(of: "\n", with: "\\n"))",
            "summary_status": "ready",
            "score_hint": 90
          },
          "summary_markdown": "\(summary.replacingOccurrences(of: "\n", with: "\\n"))",
          "warnings": [],
          "error": "",
          "body_complete": true,
          "body_text": "Full body text."
        }
        """
        return try JSONDecoder().decode(NewsReadResult.self, from: Data(json.utf8))
    }

    func testArticleURL_prefersArticleThenSkim() throws {
        let detail = makeDetail(id: "a1")
        let skimJSON = """
        {"id":"skim1","title":"Skim","url":"https://example.com/skim","viewpoints":[],"quotes":[],"meta":{},"reasons":[]}
        """
        let skim = try JSONDecoder().decode(NewsArticleCard.self, from: Data(skimJSON.utf8))
        XCTAssertEqual(
            NewsArticleViewModel.articleURL(article: detail, skim: skim)?.absoluteString,
            "https://example.com/a1"
        )
        XCTAssertEqual(
            NewsArticleViewModel.articleURL(article: nil, skim: skim)?.absoluteString,
            "https://example.com/skim"
        )
    }

    func testLoad_readySummary_skipsReadPost() async {
        let mock = MockNewsArticleService()
        mock.fetchResult = makeDetail(summaryStatus: "ready", summaryMarkdown: "## Cached\nDone.")
        let vm = NewsArticleViewModel()

        await vm.load(articleId: "art1", service: mock)

        XCTAssertEqual(mock.readCallCount, 0)
        XCTAssertEqual(vm.summaryMarkdown, "## Cached\nDone.")
        XCTAssertFalse(vm.isRefreshingSummary)
    }

    func testLoad_readSuccess_populatesSummary() async throws {
        let mock = MockNewsArticleService()
        mock.fetchResult = makeDetail(summaryStatus: "pending")
        mock.readResult = try makeReadResult(summary: "## 总结\nFresh.")
        let vm = NewsArticleViewModel()

        await vm.load(articleId: "art1", service: mock)

        XCTAssertEqual(mock.readCallCount, 1)
        XCTAssertFalse(mock.lastForceRefetch)
        XCTAssertEqual(vm.summaryMarkdown, "## 总结\nFresh.")
        XCTAssertEqual(vm.bodyText, "Full body text.")
        XCTAssertFalse(vm.isRefreshingSummary)
    }

    func testLoad_readFailure_showsError_keepsSkim() async {
        let mock = MockNewsArticleService()
        mock.fetchResult = makeDetail(summaryStatus: "pending")
        mock.readError = NSError(domain: "test", code: 1, userInfo: [NSLocalizedDescriptionKey: "read failed"])
        let vm = NewsArticleViewModel()

        await vm.load(articleId: "art1", service: mock)

        XCTAssertEqual(vm.errorMessage, "read failed")
        XCTAssertFalse(vm.isRefreshingSummary)
    }

    func testLoad_timeout_showsError() async {
        let mock = MockNewsArticleService()
        mock.fetchResult = makeDetail(summaryStatus: "pending")
        mock.readDelay = 0.2
        mock.readResult = try? makeReadResult()
        let vm = NewsArticleViewModel()
        vm.readTimeoutSeconds = 0.05

        await vm.load(articleId: "art1", service: mock)

        XCTAssertEqual(vm.errorMessage, NewsReadTimeoutError().errorDescription)
        XCTAssertFalse(vm.isRefreshingSummary)
    }

    func testCancelLoad_stopsRefreshing() async {
        let mock = MockNewsArticleService()
        mock.fetchResult = makeDetail(summaryStatus: "pending")
        mock.readDelay = 2.0
        mock.readResult = try? makeReadResult()
        let vm = NewsArticleViewModel()

        let loadTask = Task { await vm.load(articleId: "art1", service: mock) }
        try? await Task.sleep(nanoseconds: 50_000_000)
        vm.cancelLoad()
        await loadTask.value

        XCTAssertFalse(vm.isRefreshingSummary)
    }

    func testRetryLoad_callsReadAgain() async throws {
        let mock = MockNewsArticleService()
        mock.fetchResult = makeDetail(summaryStatus: "ready", summaryMarkdown: "## Cached")
        mock.readResult = try makeReadResult(summary: "## 总结\nForced.")
        let vm = NewsArticleViewModel()

        await vm.load(articleId: "art1", service: mock)
        XCTAssertEqual(mock.readCallCount, 0)

        await vm.retryLoad(service: mock)

        XCTAssertEqual(mock.readCallCount, 1)
        XCTAssertTrue(mock.lastForceRefetch)
        XCTAssertEqual(vm.summaryMarkdown, "## 总结\nForced.")
    }

    func testSendChat_success_appendsAssistant() async {
        let mock = MockNewsArticleService()
        mock.fetchResult = makeDetail(summaryStatus: "ready", summaryMarkdown: "## Cached")
        mock.chatResult = ChatResponse(
            answer: "Assistant reply",
            citations: [],
            web_refs: nil,
            evidence_sufficient: true
        )
        let vm = NewsArticleViewModel()
        await vm.load(articleId: "art1", service: mock)

        await vm.sendChat("Hello?", service: mock)

        XCTAssertEqual(vm.messages.count, 2)
        XCTAssertEqual(vm.messages[0].role, "user")
        XCTAssertEqual(vm.messages[0].content, "Hello?")
        XCTAssertEqual(vm.messages[1].role, "assistant")
        XCTAssertEqual(vm.messages[1].content, "Assistant reply")
        XCTAssertFalse(vm.isSending)
    }

    func testSendChat_failure_showsErrorMessage() async {
        let mock = MockNewsArticleService()
        mock.fetchResult = makeDetail(summaryStatus: "ready", summaryMarkdown: "## Cached")
        mock.chatError = NSError(domain: "test", code: 1, userInfo: [NSLocalizedDescriptionKey: "chat down"])
        let vm = NewsArticleViewModel()
        await vm.load(articleId: "art1", service: mock)

        await vm.sendChat("Hello?", service: mock)

        XCTAssertEqual(vm.messages.count, 2)
        XCTAssertTrue(vm.messages[1].content.hasPrefix("深聊失败："))
        XCTAssertTrue(vm.messages[1].content.contains("chat down"))
        XCTAssertFalse(vm.isSending)
    }

    func testSendChat_whitespaceOnly_isIgnored() async {
        let mock = MockNewsArticleService()
        mock.fetchResult = makeDetail(summaryStatus: "ready", summaryMarkdown: "## Cached")
        let vm = NewsArticleViewModel()
        await vm.load(articleId: "art1", service: mock)

        await vm.sendChat("   ", service: mock)

        XCTAssertTrue(vm.messages.isEmpty)
        XCTAssertFalse(vm.isSending)
    }

    func testSendChat_setsIsSendingDuringRequest() async {
        let mock = MockNewsArticleService()
        mock.fetchResult = makeDetail(summaryStatus: "ready", summaryMarkdown: "## Cached")
        mock.chatDelay = 0.1
        mock.chatResult = ChatResponse(
            answer: "Reply",
            citations: [],
            web_refs: nil,
            evidence_sufficient: true
        )
        let vm = NewsArticleViewModel()
        await vm.load(articleId: "art1", service: mock)

        let sendTask = Task { await vm.sendChat("Question?", service: mock) }
        try? await Task.sleep(nanoseconds: 20_000_000)
        XCTAssertTrue(vm.isSending)
        await sendTask.value
        XCTAssertFalse(vm.isSending)
    }
}

@MainActor
private final class MockNewsArticleService: NewsArticleServing {
    var fetchResult: NewsArticleDetail?
    var fetchError: Error?
    var readResult: NewsReadResult?
    var readError: Error?
    var readDelay: TimeInterval = 0
    var readCallCount = 0
    var lastForceRefetch = false
    var chatResult: ChatResponse?
    var chatError: Error?
    var chatDelay: TimeInterval = 0

    func fetchNewsArticle(id: String) async throws -> NewsArticleDetail {
        if let fetchError { throw fetchError }
        guard let fetchResult else {
            throw NSError(domain: "MockNewsArticleService", code: 1, userInfo: [NSLocalizedDescriptionKey: "no fetch"])
        }
        return fetchResult
    }

    func readNewsArticle(id: String, forceRefetch: Bool, skimOnly: Bool) async throws -> NewsReadResult {
        readCallCount += 1
        lastForceRefetch = forceRefetch
        _ = skimOnly
        if readDelay > 0 {
            try await Task.sleep(nanoseconds: UInt64(readDelay * 1_000_000_000))
        }
        if let readError { throw readError }
        guard let readResult else {
            throw NSError(domain: "MockNewsArticleService", code: 2, userInfo: [NSLocalizedDescriptionKey: "no read"])
        }
        return readResult
    }

    func newsChatStream(
        articleId: String,
        message: String,
        quote: String?,
        onToken: @escaping (String) -> Void
    ) async throws -> ChatResponse {
        if chatDelay > 0 {
            try await Task.sleep(nanoseconds: UInt64(chatDelay * 1_000_000_000))
        }
        if let chatError { throw chatError }
        guard let chatResult else {
            throw NSError(domain: "MockNewsArticleService", code: 3, userInfo: [NSLocalizedDescriptionKey: "no chat"])
        }
        return chatResult
    }
}
