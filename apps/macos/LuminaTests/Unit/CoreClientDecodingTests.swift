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
        XCTAssertEqual(complete.progressLabel, "未读")

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

    func testBookSummary_completedSummaryUsesReadingStatus() {
        var book = BookSummary(
            id: "b1",
            title: "Reading",
            status: "summarized",
            segment_count: 10,
            summary_ready_count: 10,
            summary_total_count: 10
        )

        XCTAssertTrue(book.hasCompletedSummary)
        XCTAssertEqual(book.readingCurrent, 0)
        XCTAssertEqual(book.readingStatusLabel, "未读")
        XCTAssertEqual(book.progressLabel, "未读")

        book.last_opened_at = "2026-08-22T12:00:00Z"
        book.current_segment_index = 4
        XCTAssertEqual(book.readingCurrent, 5)
        XCTAssertEqual(book.readingStatusLabel, "在读 · 5/10 段")
        XCTAssertEqual(book.progressLabel, "在读 · 5/10 段")

        book.current_segment_index = 9
        XCTAssertEqual(book.readingCurrent, 10)
        XCTAssertEqual(book.readingStatusLabel, "已读完")
        XCTAssertEqual(book.readingProgressBucket, .finished)

        book.current_segment_index = 2
        XCTAssertEqual(book.readingStatusLabel, "在读 · 3/10 段")

        book.current_segment_index = -3
        XCTAssertEqual(book.readingCurrent, 1)
        XCTAssertEqual(book.readingStatusLabel, "在读 · 1/10 段")

        book.current_segment_index = 100
        XCTAssertEqual(book.readingCurrent, 10)
        XCTAssertEqual(book.readingStatusLabel, "已读完")
        XCTAssertEqual(book.readingProgressBucket, .finished)
    }

    func testBookSummary_singleSegmentOpenedStaysReading() {
        var book = BookSummary(
            id: "short",
            title: "Short",
            status: "reading",
            segment_count: 1,
            last_opened_at: "2026-08-22T12:00:00Z",
            current_segment_index: 0
        )
        XCTAssertEqual(book.readingProgressBucket, .reading)
        XCTAssertEqual(book.readingStatusLabel, "在读 · 1/1 段")
        book.last_opened_at = nil
        XCTAssertEqual(book.readingProgressBucket, .unread)
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

    func testBookSummary_decodesResegmentMetadata() throws {
        let json = """
        {
          "books": [{
            "id": "b1",
            "title": "Sample",
            "status": "reading",
            "segment_count": 7,
            "total_char_count": 17500,
            "chunk_target_chars": 2500,
            "chunker_version": "5",
            "processing_kind": "resegment"
          }]
        }
        """
        let data = Data(json.utf8)
        let resp = try JSONDecoder().decode(BooksListResponse.self, from: data)
        XCTAssertEqual(resp.books[0].total_char_count, 17_500)
        XCTAssertEqual(resp.books[0].chunk_target_chars, 2_500)
        XCTAssertEqual(resp.books[0].chunker_version, "5")
        XCTAssertEqual(resp.books[0].processing_kind, "resegment")
    }

    func testBookSummary_canResegmentRequiresReadyBook() {
        let ready = BookSummary(
            id: "b1", title: "Ready", status: "reading", segment_count: 7
        )
        XCTAssertTrue(ready.canResegment)
        XCTAssertTrue(
            LibraryBookContextMenuPolicy.actions(for: ready).contains(.resegment)
        )
        XCTAssertTrue(LibraryBookContextMenuPolicy.isEnabled(.resegment, for: ready))

        let processing = BookSummary(
            id: "b2", title: "Busy", status: "processing", segment_count: 7,
            processing_kind: "resegment"
        )
        XCTAssertFalse(processing.canResegment)
        XCTAssertTrue(
            LibraryBookContextMenuPolicy.actions(for: processing).contains(.resegment)
        )
        XCTAssertFalse(LibraryBookContextMenuPolicy.isEnabled(.resegment, for: processing))

        let failed = BookSummary(
            id: "b3", title: "Fail", status: "error", segment_count: 0
        )
        XCTAssertFalse(failed.canResegment)
        XCTAssertFalse(LibraryBookContextMenuPolicy.isEnabled(.resegment, for: failed))

        let unsegmented = BookSummary(
            id: "b4", title: "Empty", status: "unread", segment_count: 0
        )
        XCTAssertFalse(unsegmented.canResegment)
    }

    func testBookSummary_errorStatusIncludesIngestError() throws {
        let json = """
        {
          "books": [{
            "id": "b1",
            "title": "金阁寺",
            "status": "error",
            "segment_count": 0,
            "ingest_error": "unknown encoding: utf-8-sig"
          }]
        }
        """
        let data = Data(json.utf8)
        let resp = try JSONDecoder().decode(BooksListResponse.self, from: data)
        XCTAssertEqual(resp.books[0].ingest_error, "unknown encoding: utf-8-sig")
        XCTAssertEqual(resp.books[0].statusLabel, "导入失败：unknown encoding: utf-8-sig")

        let bare = BookSummary(id: "b2", title: "失败", status: "error", segment_count: 0)
        XCTAssertEqual(bare.statusLabel, "导入失败")
    }

    func testAppSettings_decodesDefaultSettings() throws {
        let data = try loadFixture("settings_default")
        let settings = try JSONDecoder().decode(AppSettings.self, from: data)
        XCTAssertEqual(settings.target_language, "zh-CN")
        XCTAssertFalse(settings.debug_mode)
        XCTAssertFalse(settings.auto_start_summary)
        XCTAssertEqual(settings.ocr_cloud_base_url, "")
        XCTAssertEqual(settings.ocr_cloud_model, "")
        XCTAssertNil(settings.ocr_cloud_api_key)
        XCTAssertEqual(settings.ocr_cloud_timeout_seconds, 60)
        XCTAssertEqual(settings.models.resource(id: "ollama")?.model, "qwen3.5:4b")
        XCTAssertEqual(settings.models.resource(id: "openai")?.advanced_model, "gpt-4o")
        XCTAssertEqual(settings.models.resource(id: "openai")?.base_url, "https://api.openai.com/v1")
        XCTAssertEqual(settings.models.chat.priority, ["openai", "ollama"])
        XCTAssertEqual(settings.models.summarize.priority.first, "ollama")
        XCTAssertFalse(settings.prompts.segment.isEmpty)
        XCTAssertFalse(settings.prompts_defaults.segment.isEmpty)
        XCTAssertTrue(settings.prompts.segment.contains("{text}"))
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

    func testBookSummary_decodesSummarizeState() throws {
        let json = """
        {
          "books": [{
            "id": "b1",
            "title": "Sample",
            "status": "reading",
            "segment_count": 5,
            "summary_ready_count": 1,
            "summary_total_count": 5,
            "summarize_state": "queued",
            "summarize_queued_count": 3
          }]
        }
        """
        let resp = try JSONDecoder().decode(BooksListResponse.self, from: json.data(using: .utf8)!)
        XCTAssertEqual(resp.books[0].summarize_state, "queued")
        XCTAssertEqual(resp.books[0].summarizeQueuedCount, 3)
        XCTAssertTrue(resp.books[0].canStopSummarize)
        XCTAssertFalse(resp.books[0].canStartSummarize)
    }

    func testBookSummary_decodesIndexStatus() throws {
        let json = """
        {
          "books": [{
            "id": "b1",
            "title": "Sample",
            "status": "summarized",
            "segment_count": 5,
            "summary_ready_count": 5,
            "summary_total_count": 5,
            "index_status": "ready"
          }]
        }
        """
        let resp = try JSONDecoder().decode(BooksListResponse.self, from: json.data(using: .utf8)!)
        XCTAssertEqual(resp.books[0].index_status, "ready")
        XCTAssertTrue(resp.books[0].canChatBook)
        XCTAssertEqual(resp.books[0].bookIndexLabel, "全书")
    }

    func testSummarizeOverview_decodesCounts() throws {
        let json = """
        {
          "counts": {
            "running": 1,
            "queued": 2,
            "paused": 0,
            "idle": 3,
            "summarized": 4
          },
          "user_paused_all": false
        }
        """
        let overview = try JSONDecoder().decode(SummarizeOverview.self, from: json.data(using: .utf8)!)
        XCTAssertEqual(overview.activeCount, 3)
        XCTAssertEqual(overview.counts.idle, 3)
        XCTAssertFalse(overview.user_paused_all)
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

    func testChatResponse_fromSSEDone_parsesMetrics() {
        let obj: [String: Any] = [
            "type": "done",
            "answer": "hello",
            "evidence_sufficient": true,
            "provider": "openai",
            "model": "gpt-4o-mini",
            "duration_ms": 3200,
            "prompt_tokens": 1200,
            "completion_tokens": 380,
            "total_tokens": 1580,
            "tps": 118.7,
            "web_refs": [
                ["title": "Example", "url": "https://example.com", "source": "ddgs"],
            ],
        ]
        let resp = ChatResponse.fromSSEDone(obj, citations: [])
        XCTAssertEqual(resp.answer, "hello")
        XCTAssertEqual(resp.webRefs.first?.url, "https://example.com")
        XCTAssertEqual(resp.webRefs.first?.title, "Example")
        XCTAssertEqual(resp.provider, "openai")
        XCTAssertEqual(resp.model, "gpt-4o-mini")
        XCTAssertEqual(resp.duration_ms, 3200)
        XCTAssertEqual(resp.prompt_tokens, 1200)
        XCTAssertEqual(resp.completion_tokens, 380)
        XCTAssertEqual(resp.total_tokens, 1580)
        XCTAssertEqual(resp.tps, 118.7)
    }

    func testChatMetricsFormatter_buildsAttribution() {
        let label = ChatMetricsFormatter.attribution(
            provider: "openai",
            model: "gpt-4o-mini",
            tps: 118.7,
            totalTokens: 1580,
            promptTokens: 1200,
            completionTokens: 380,
            durationMs: 3200
        )
        XCTAssertEqual(label, "深聊 · OpenAI · gpt-4o-mini · 119 tok/s · 1.6k tokens · 3s")
    }

    func testChatMetricsFormatter_omitsMissingFields() {
        XCTAssertNil(
            ChatMetricsFormatter.attribution(
                provider: nil,
                model: nil,
                tps: nil,
                totalTokens: nil,
                promptTokens: nil,
                completionTokens: nil,
                durationMs: nil
            )
        )
        let label = ChatMetricsFormatter.attribution(
            provider: "ollama",
            model: "qwen3.5:4b",
            tps: nil,
            totalTokens: nil,
            promptTokens: nil,
            completionTokens: nil,
            durationMs: 1500
        )
        XCTAssertEqual(label, "深聊 · Ollama · qwen3.5:4b · 2s")
    }

    func testContextProbeStatus_decodesRecommendation() throws {
        let json = """
        {
          "resource_id": "ollama",
          "status": "done",
          "model": "qwen3.5:4b",
          "current_chars": 3500,
          "max_ok_chars": 3500,
          "recommended_chars": 2800,
          "steps": [{"chars": 1500, "ok": true, "message": ""}],
          "message": "实测后面内容仍被理解约 3500 字 · 建议分段 2800 字（80%，上限 3500）",
          "waiting_for_slot": false
        }
        """.data(using: .utf8)!
        let status = try JSONDecoder().decode(ContextProbeStatus.self, from: json)
        XCTAssertEqual(status.resource_id, "ollama")
        XCTAssertEqual(status.status, "done")
        XCTAssertEqual(status.recommended_chars, 2800)
        XCTAssertEqual(status.max_ok_chars, 3500)
        XCTAssertFalse(status.isRunning)
        XCTAssertTrue(status.displayMessage.contains("2800"))
    }

    func testSummaryTier_startDoesNotOverwriteReady() {
        XCTAssertEqual(SummaryTier.advanced.startMenuLabel, "高级摘要（仅未摘要）")
        XCTAssertEqual(SummaryTier.normal.startMenuLabel, "正常摘要")
        XCTAssertEqual(SummaryTier.advanced.regenerateMenuLabel, "高级摘要（覆盖全书）")
        XCTAssertEqual(SummaryTier.normal.regenerateMenuLabel, "正常摘要（覆盖全书）")
    }

    func testSegmentBoundaryPreview_decodesCandidates() throws {
        let json = """
        {
          "left_idx": 2,
          "right_idx": 3,
          "total_chars": 900,
          "left_char_count": 420,
          "candidates": [
            {"offset": 210, "kind": "paragraph"},
            {"offset": 420, "kind": "current"},
            {"offset": 630, "kind": "sentence"}
          ],
          "oversized_limit": 6000
        }
        """.data(using: .utf8)!
        let preview = try JSONDecoder().decode(SegmentBoundaryPreview.self, from: json)
        XCTAssertEqual(preview.left_idx, 2)
        XCTAssertEqual(preview.candidates.count, 3)
        XCTAssertEqual(preview.candidates[1].kind, "current")

        let movedJson = """
        {
          "left_idx": 2,
          "right_idx": 3,
          "left_char_count": 630,
          "right_char_count": 270,
          "left_status": "pending",
          "right_status": "pending",
          "oversized": false,
          "unchanged": false
        }
        """.data(using: .utf8)!
        let moved = try JSONDecoder().decode(SegmentBoundaryMoveResult.self, from: movedJson)
        XCTAssertEqual(moved.left_char_count, 630)
        XCTAssertFalse(moved.unchanged)
    }

    func testSegmentSummaryDetail_decodesWithoutRawText() throws {
        let json = """
        {
          "idx": 0,
          "summary_json": "{\\"sentences\\":[\\"x\\"]}",
          "summary_status": "ready",
          "label": "段 1",
          "anchor_label": "§1"
        }
        """.data(using: .utf8)!
        let detail = try JSONDecoder().decode(SegmentSummaryDetail.self, from: json)
        XCTAssertEqual(detail.idx, 0)
        XCTAssertEqual(detail.summary_status, "ready")
        XCTAssertEqual(detail.label, "段 1")
        XCTAssertNotNil(detail.summary_json)
    }
}
