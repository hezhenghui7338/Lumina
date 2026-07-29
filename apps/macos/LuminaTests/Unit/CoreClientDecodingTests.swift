import XCTest
@testable import Lumina

/// E2E-BOOT-01: Ensure startup API JSON decodes into Swift models (regression for is_favorite int/bool).
final class CoreClientDecodingTests: XCTestCase {
    private struct BooksListResponse: Decodable {
        let books: [BookSummary]
    }

    private func loadFixture(_ name: String) throws -> Data {
        let bundle = Bundle(for: CoreClientDecodingTests.self)
        guard let url = bundle.url(forResource: name, withExtension: "json") else {
            throw NSError(
                domain: "CoreClientDecodingTests",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: "Missing fixture \(name).json"]
            )
        }
        return try Data(contentsOf: url)
    }

    func testBookSummary_decodesBoolFavorite() throws {
        let data = try loadFixture("books_list_favorite_bool")
        let resp = try JSONDecoder().decode(BooksListResponse.self, from: data)
        XCTAssertEqual(resp.books.count, 1)
        XCTAssertTrue(resp.books[0].isFavorite)
        XCTAssertEqual(resp.books[0].summaryReady, 1)
        XCTAssertEqual(resp.books[0].summaryTotal, 3)
        XCTAssertEqual(resp.books[0].progressLabel, "未读 · 摘要 1/3")
    }

    func testBookSummary_decodesLegacyIntFavorite() throws {
        let data = try loadFixture("books_list_favorite_int")
        let resp = try JSONDecoder().decode(BooksListResponse.self, from: data)
        XCTAssertEqual(resp.books.count, 1)
        XCTAssertTrue(resp.books[0].isFavorite)
    }

    func testBookSummary_summaryProgressLabel() throws {
        let partial = BookSummary(
            id: "b1",
            title: "Partial",
            status: "reading",
            segment_count: 10,
            summary_ready_count: 3,
            summary_total_count: 10
        )
        XCTAssertEqual(partial.progressLabel, "在读 · 摘要 3/10")
        XCTAssertEqual(partial.summaryReady, 3)
        XCTAssertEqual(partial.summaryTotal, 10)

        let complete = BookSummary(
            id: "b2",
            title: "Done",
            status: "summarized",
            segment_count: 10,
            summary_ready_count: 10,
            summary_total_count: 10
        )
        XCTAssertEqual(complete.progressLabel, "已摘要")

        let processing = BookSummary(
            id: "b3",
            title: "Importing",
            status: "processing",
            segment_count: nil,
            summary_ready_count: nil,
            summary_total_count: nil
        )
        XCTAssertEqual(processing.progressLabel, "处理中")
    }

    func testBookSummary_decodesLanguageFields() throws {
        let json = """
        {
          "books": [{
            "id": "b1",
            "title": "Sample",
            "status": "reading",
            "segment_count": 3,
            "language": "en",
            "target_language": "zh-CN"
          }]
        }
        """
        let data = Data(json.utf8)
        let resp = try JSONDecoder().decode(BooksListResponse.self, from: data)
        XCTAssertEqual(resp.books[0].language, "en")
        XCTAssertEqual(resp.books[0].target_language, "zh-CN")
        XCTAssertTrue(
            BookLanguageMatcher.needsTranslation(
                bookLanguage: resp.books[0].language,
                bookTargetLanguage: resp.books[0].target_language,
                globalTargetLanguage: "zh-CN",
                textSample: nil
            )
        )
    }

    func testAppSettings_decodesDefaultSettings() throws {
        let data = try loadFixture("settings_default")
        let settings = try JSONDecoder().decode(AppSettings.self, from: data)
        XCTAssertEqual(settings.target_language, "zh-CN")
        XCTAssertFalse(settings.debug_mode)
        XCTAssertEqual(settings.models.resource(id: "ollama")?.model, "qwen3.5:4b")
        XCTAssertEqual(settings.models.resource(id: "openai")?.base_url, "https://api.openai.com/v1")
        XCTAssertEqual(settings.models.chat.priority, ["openai", "ollama"])
        XCTAssertEqual(settings.models.summarize.priority.first, "ollama")
    }

    func testNewsBrief_decodesEmptyBrief() throws {
        let data = try loadFixture("news_brief_empty")
        let brief = try JSONDecoder().decode(NewsBrief.self, from: data)
        XCTAssertEqual(brief.count, 0)
        XCTAssertTrue(brief.articles.isEmpty)
        XCTAssertEqual(brief.date, "2026-07-28")
    }

    func testNewsBrief_decodesSourceFields() throws {
        let data = try loadFixture("news_brief_sample")
        let brief = try JSONDecoder().decode(NewsBrief.self, from: data)
        XCTAssertEqual(brief.count, 2)
        XCTAssertEqual(brief.articles[0].source_id, "src-hn")
        XCTAssertEqual(brief.articles[0].source_title, "Hacker News")
        XCTAssertEqual(brief.articles[0].source, "Hacker News")
        XCTAssertEqual(brief.articles[1].source_title, "BestBlogs AI")
    }

    func testNewsSources_decodesPresetFlag() throws {
        struct Resp: Decodable { let sources: [NewsSource] }
        let data = try loadFixture("news_sources_sample")
        let resp = try JSONDecoder().decode(Resp.self, from: data)
        XCTAssertEqual(resp.sources.count, 2)
        XCTAssertTrue(resp.sources[0].isPreset)
        XCTAssertFalse(resp.sources[1].isPreset)
        XCTAssertEqual(resp.sources[1].title, "量子位")
    }

    func testNewsReadResult_decodesReadyPayload() throws {
        let data = try loadFixture("news_read_result_ready")
        let result = try JSONDecoder().decode(NewsReadResult.self, from: data)
        XCTAssertEqual(result.article.id, "art-ready")
        XCTAssertEqual(result.article.summary_status, "ready")
        XCTAssertTrue(result.summary_markdown.contains("总结"))
        XCTAssertEqual(result.warnings.count, 1)
        XCTAssertEqual(result.body_text, "推理成本显著下降。云厂商集体降价。")
        XCTAssertTrue(result.body_complete)
    }

    func testBookSummary_decodesSummarizeActiveAndSegmentMetrics() throws {
        let json = """
        {
          "books": [{
            "id": "b1",
            "title": "Sample",
            "status": "reading",
            "segment_count": 5,
            "summary_ready_count": 2,
            "summary_total_count": 5,
            "summarize_active": {
              "segment_idx": 2,
              "started_at": "2026-07-29T12:00:00+00:00",
              "llm_attempt": 2,
              "max_llm_attempts": 2
            }
          }]
        }
        """
        let resp = try JSONDecoder().decode(BooksListResponse.self, from: json.data(using: .utf8)!)
        XCTAssertEqual(resp.books[0].summarize_active?.segment_idx, 2)
        XCTAssertEqual(resp.books[0].summarize_active?.llm_attempt, 2)
        XCTAssertEqual(resp.books[0].summarize_active?.max_llm_attempts, 2)
        XCTAssertNotNil(resp.books[0].summarize_active?.startedAtDate)
    }

    func testSegmentRow_decodesSummaryMetrics() throws {
        let json = """
        {
          "id": "s1",
          "idx": 0,
          "summary_status": "ready",
          "retry_count": 0,
          "summary_duration_s": 62.5,
          "summary_llm_attempts": 2
        }
        """
        let segment = try JSONDecoder().decode(SegmentRow.self, from: json.data(using: .utf8)!)
        XCTAssertEqual(segment.summary_duration_s, 62.5)
        XCTAssertEqual(segment.summary_llm_attempts, 2)
    }

    func testSummaryMetricsFormatter_formatsDurationAndAttempts() {
        XCTAssertEqual(SummaryMetricsFormatter.duration(seconds: 45), "45s")
        XCTAssertEqual(SummaryMetricsFormatter.duration(seconds: 62), "1m 2s")
        XCTAssertEqual(
            SummaryMetricsFormatter.attemptLabel(attempt: 2, maxAttempts: 2),
            "第 2/2 次尝试"
        )
        XCTAssertEqual(
            SummaryMetricsFormatter.completedMetricsLabel(durationS: 62, llmAttempts: 2),
            "1m 2s · 2 次尝试"
        )
    }
}
