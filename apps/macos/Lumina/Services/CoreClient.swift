import Foundation

struct BookSummary: Codable, Identifiable, Hashable {
    let id: String
    let title: String
    let status: String
    let segment_count: Int?
    var is_favorite: Bool?
    var category: String?
    var last_opened_at: String?
    var current_segment_index: Int?
    var author: String?
    var created_at: String?
    var total_char_count: Int?
    var summary_ready_count: Int?
    var summary_total_count: Int?
    var chunker_version: String?
    var language: String?
    var target_language: String?

    enum CodingKeys: String, CodingKey {
        case id, title, status, segment_count, is_favorite, category
        case last_opened_at, current_segment_index, author, created_at
        case total_char_count, summary_ready_count, summary_total_count, chunker_version
        case language, target_language
    }

    init(
        id: String,
        title: String,
        status: String,
        segment_count: Int?,
        is_favorite: Bool? = nil,
        category: String? = nil,
        last_opened_at: String? = nil,
        current_segment_index: Int? = nil,
        author: String? = nil,
        created_at: String? = nil,
        total_char_count: Int? = nil,
        summary_ready_count: Int? = nil,
        summary_total_count: Int? = nil,
        chunker_version: String? = nil,
        language: String? = nil,
        target_language: String? = nil
    ) {
        self.id = id
        self.title = title
        self.status = status
        self.segment_count = segment_count
        self.is_favorite = is_favorite
        self.category = category
        self.last_opened_at = last_opened_at
        self.current_segment_index = current_segment_index
        self.author = author
        self.created_at = created_at
        self.total_char_count = total_char_count
        self.summary_ready_count = summary_ready_count
        self.summary_total_count = summary_total_count
        self.chunker_version = chunker_version
        self.language = language
        self.target_language = target_language
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        title = try c.decode(String.self, forKey: .title)
        status = try c.decode(String.self, forKey: .status)
        segment_count = try c.decodeIfPresent(Int.self, forKey: .segment_count)
        if let bool = try? c.decode(Bool.self, forKey: .is_favorite) {
            is_favorite = bool
        } else if let int = try? c.decode(Int.self, forKey: .is_favorite) {
            is_favorite = int != 0
        } else if c.contains(.is_favorite) {
            is_favorite = nil
        } else {
            is_favorite = nil
        }
        category = try c.decodeIfPresent(String.self, forKey: .category)
        last_opened_at = try c.decodeIfPresent(String.self, forKey: .last_opened_at)
        current_segment_index = try c.decodeIfPresent(Int.self, forKey: .current_segment_index)
        author = try c.decodeIfPresent(String.self, forKey: .author)
        created_at = try c.decodeIfPresent(String.self, forKey: .created_at)
        total_char_count = try c.decodeIfPresent(Int.self, forKey: .total_char_count)
        summary_ready_count = try c.decodeIfPresent(Int.self, forKey: .summary_ready_count)
        summary_total_count = try c.decodeIfPresent(Int.self, forKey: .summary_total_count)
        chunker_version = try c.decodeIfPresent(String.self, forKey: .chunker_version)
        language = try c.decodeIfPresent(String.self, forKey: .language)
        target_language = try c.decodeIfPresent(String.self, forKey: .target_language)
    }

    var isFavorite: Bool { is_favorite ?? false }

    var summaryTotal: Int { summary_total_count ?? segment_count ?? 0 }

    var summaryReady: Int { summary_ready_count ?? 0 }

    var progressLabel: String {
        let total = summaryTotal
        if status == "processing" { return statusLabel }
        guard total > 0 else { return statusLabel }
        let ready = summaryReady
        if ready >= total { return "已摘要" }
        return "\(statusLabel) · 摘要 \(ready)/\(total)"
    }

    var isProcessing: Bool { status == "processing" }

    var statusLabel: String {
        switch status {
        case "unread": return "未读"
        case "reading": return "在读"
        case "summarized": return "已摘要"
        case "processing": return "处理中"
        case "error": return "导入失败"
        default: return status
        }
    }
}

struct ImportConflictError: LocalizedError {
    let existingBookId: String
    let title: String
    let path: String

    var errorDescription: String? {
        "《\(title)》已在书库中"
    }
}

enum LibraryCollection: String, CaseIterable, Identifiable {
    case all, unread, reading, summarized

    var id: String { rawValue }

    var label: String {
        switch self {
        case .all: return "全部"
        case .unread: return "未读"
        case .reading: return "在读"
        case .summarized: return "已摘要"
        }
    }

    var queryValue: String { rawValue }
}

enum LibrarySort: String, CaseIterable, Identifiable {
    case recent, added, title, favorite

    var id: String { rawValue }

    var label: String {
        switch self {
        case .recent: return "最近打开"
        case .added: return "添加时间"
        case .title: return "标题"
        case .favorite: return "收藏优先"
        }
    }

    var queryValue: String { rawValue }
}

struct OpenBookResponse: Codable {
    let status: String
    let current_segment_index: Int
}

struct SegmentRow: Codable, Identifiable, Hashable {
    let id: String
    let idx: Int
    var label: String?
    let chapter: String?
    var summary_status: String
    var summary_json: String?
    let raw_text: String?
    var translation: String?
    var anchor_label: String?
    var summary_provider: String?
    var summary_model: String?
    var char_count: Int?
}

struct ChatCitation: Codable {
    let segment_index: Int
    let label: String
}

struct ChatResponse: Codable {
    let answer: String
    let citations: [ChatCitation]
    let web_refs: [[String: String]]?
    let evidence_sufficient: Bool?
}

struct ChatMessage: Identifiable {
    let id: UUID
    let role: String
    var content: String
    var citations: [ChatCitation]

    init(role: String, content: String, citations: [ChatCitation] = []) {
        self.id = UUID()
        self.role = role
        self.content = content
        self.citations = citations
    }
}

struct ResourceStatus: Codable {
    let resource_id: String
    let provider: String
    let ready: Bool
    let probe_ok: Bool
    let key_configured: Bool
    let model_ready: Bool
    let message: String?
    let available_models: [String]?
    let base_url: String?
    let installed: Bool?
    let installed_models: [String]?
    let ram_gb: String?
    let skipped: Bool?

    var displayMessage: String {
        let trimmed = message?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return trimmed.isEmpty ? (ready ? "已就绪" : "未就绪") : trimmed
    }
}

struct SearchHit: Codable, Identifiable, Hashable {
    var id: String {
        [book_id, segment_id ?? "", note_id ?? "", kind].joined(separator: ":")
    }
    let book_id: String
    let segment_id: String?
    let note_id: String?
    let kind: String
    let title: String
    let snippet: String?
    let segment_index: Int?
}

struct NewsArticleCard: Codable, Identifiable, Hashable {
    let id: String
    let title: String
    let excerpt: String?
    let one_liner: String?
    let detail: String?
    let viewpoints: [String]
    let quotes: [String]
    let meta: [String: String]
    let reasons: [String]
    let score_hint: Double?
    let source_id: String?
    let source_title: String?
    let source: String?
    let url: String
    let published_at: String?
    let skim_rich: Bool?
    let summary_status: String?

    enum CodingKeys: String, CodingKey {
        case id, title, excerpt, one_liner, detail, viewpoints, quotes, meta
        case reasons, score_hint, source_id, source_title, source, url, published_at
        case skim_rich, summary_status
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        title = try c.decode(String.self, forKey: .title)
        excerpt = try c.decodeIfPresent(String.self, forKey: .excerpt)
        one_liner = try c.decodeIfPresent(String.self, forKey: .one_liner)
        detail = try c.decodeIfPresent(String.self, forKey: .detail)
        viewpoints = try c.decodeIfPresent([String].self, forKey: .viewpoints) ?? []
        quotes = try c.decodeIfPresent([String].self, forKey: .quotes) ?? []
        meta = try c.decodeIfPresent([String: String].self, forKey: .meta) ?? [:]
        reasons = try c.decodeIfPresent([String].self, forKey: .reasons) ?? []
        score_hint = try c.decodeIfPresent(Double.self, forKey: .score_hint)
        source_id = try c.decodeIfPresent(String.self, forKey: .source_id)
        source_title = try c.decodeIfPresent(String.self, forKey: .source_title)
        source = try c.decodeIfPresent(String.self, forKey: .source)
        url = try c.decode(String.self, forKey: .url)
        published_at = try c.decodeIfPresent(String.self, forKey: .published_at)
        skim_rich = try c.decodeIfPresent(Bool.self, forKey: .skim_rich)
        summary_status = try c.decodeIfPresent(String.self, forKey: .summary_status)
    }

    /// True when RSS skim is too sparse and LLM summary should be generated on demand.
    var needsLLMSkim: Bool {
        if skim_rich == true { return false }
        if let detail, detail.count >= 80 { return false }
        if viewpoints.count >= 2 { return false }
        if !quotes.isEmpty { return false }
        return true
    }

    var hasCachedLLMSummary: Bool {
        summary_status == "ready"
    }

    func hash(into hasher: inout Hasher) { hasher.combine(id) }
    static func == (lhs: NewsArticleCard, rhs: NewsArticleCard) -> Bool { lhs.id == rhs.id }
}

struct NewsSource: Codable, Identifiable, Hashable {
    let id: String
    let url: String
    let title: String?
    let created_at: String?
    let is_preset: Bool?

    var isPreset: Bool { is_preset ?? false }
}

struct NewsBrief: Codable {
    let date: String
    let count: Int
    let articles: [NewsArticleCard]
}

/// HTTP client for lumina-core. Not MainActor-isolated: network I/O and JSON
/// decoding must not block the UI thread (PRD 永不卡住用户).
final class CoreClient: ObservableObject {
    let baseURL: URL
    private let session = URLSession.shared
    private static let longSession: URLSession = {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 300
        config.timeoutIntervalForResource = 600
        return URLSession(configuration: config)
    }()

    init(baseURL: URL) {
        self.baseURL = baseURL
    }

    func listBooks(
        collection: LibraryCollection = .all,
        sort: LibrarySort = .recent
    ) async throws -> [BookSummary] {
        let data = try await get(path: "/books", queryItems: [
            URLQueryItem(name: "collection", value: collection.queryValue),
            URLQueryItem(name: "sort", value: sort.queryValue),
        ])
        struct Resp: Codable { let books: [BookSummary] }
        return try await Self.decode(Resp.self, from: data).books
    }

    func updateBook(
        id: String,
        isFavorite: Bool? = nil,
        category: String? = nil,
        title: String? = nil
    ) async throws -> BookSummary {
        struct Body: Codable {
            let is_favorite: Bool?
            let category: String?
            let title: String?
        }
        let body = try JSONEncoder().encode(Body(
            is_favorite: isFavorite,
            category: category,
            title: title
        ))
        let data = try await patch(path: "/books/\(id)", body: body)
        return try await Self.decode(BookSummary.self, from: data)
    }

    func deleteBook(id: String) async throws {
        _ = try await delete(path: "/books/\(id)")
    }

    func deleteBooks(ids: [String]) async throws {
        for id in ids {
            try await deleteBook(id: id)
        }
    }

    func setBooksFavorite(ids: [String], isFavorite: Bool) async throws -> [BookSummary] {
        var updated: [BookSummary] = []
        for id in ids {
            updated.append(try await updateBook(id: id, isFavorite: isFavorite))
        }
        return updated
    }

    func classifyBook(id: String) async throws {
        _ = try await post(path: "/books/\(id)/classify", body: Data("{}".utf8))
    }

    func importBook(path: String, overwrite: Bool = false) async throws -> BookSummary {
        struct Body: Codable { let paths: [String]; let overwrite: Bool }
        let body = try JSONEncoder().encode(Body(paths: [path], overwrite: overwrite))
        let data = try await postAllowingConflict(path: "/books/import", body: body, importPath: path)
        struct Resp: Codable { let books: [ImportResult] }
        struct ImportResult: Codable { let book_id: String; let title: String; let status: String }
        let resp = try await Self.decode(Resp.self, from: data)
        guard let first = resp.books.first else { throw URLError(.badServerResponse) }
        return BookSummary(
            id: first.book_id,
            title: first.title,
            status: first.status,
            segment_count: nil,
            is_favorite: nil,
            category: nil,
            last_opened_at: nil,
            current_segment_index: nil,
            author: nil,
            created_at: nil
        )
    }

    private func postAllowingConflict(path: String, body: Data, importPath: String) async throws -> Data {
        try await withConnectionRetry {
            var request = URLRequest(url: self.url(path: path))
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = body
            let (data, resp) = try await self.session.data(for: request)
            if let http = resp as? HTTPURLResponse, http.statusCode == 409 {
                throw Self.parseImportConflict(data: data, path: importPath)
            }
            try self.validate(resp: resp, data: data)
            return data
        }
    }

    private static func parseImportConflict(data: Data, path: String) -> ImportConflictError {
        if let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let detail = obj["detail"] as? [String: Any],
           let bookId = detail["existing_book_id"] as? String {
            let title = detail["title"] as? String ?? "未知书名"
            return ImportConflictError(existingBookId: bookId, title: title, path: path)
        }
        return ImportConflictError(existingBookId: "", title: "未知书名", path: path)
    }

    func openBook(id: String) async throws -> OpenBookResponse {
        let data = try await post(path: "/books/\(id)/open", body: Data("{}".utf8))
        return try await Self.decode(OpenBookResponse.self, from: data)
    }

    func fetchBook(id: String) async throws -> BookSummary {
        let data = try await get(path: "/books/\(id)")
        return try await Self.decode(BookSummary.self, from: data)
    }

    func saveReadingProgress(bookId: String, segmentIndex: Int) async throws {
        struct Body: Codable { let segment_index: Int }
        let body = try JSONEncoder().encode(Body(segment_index: segmentIndex))
        _ = try await patch(path: "/books/\(bookId)/reading-progress", body: body)
    }

    func listSegments(bookId: String) async throws -> [SegmentRow] {
        let data = try await get(path: "/books/\(bookId)/segments")
        struct Resp: Codable { let segments: [SegmentRow] }
        return try await Self.decode(Resp.self, from: data).segments
    }

    func getSegment(bookId: String, idx: Int) async throws -> SegmentRow {
        let data = try await get(path: "/books/\(bookId)/segments/\(idx)")
        return try await Self.decode(SegmentRow.self, from: data)
    }

    func startSummarizeAll() async throws {
        _ = try await post(path: "/books/summarize/start", body: Data("{}".utf8))
    }

    func stopSummarizeAll() async throws {
        _ = try await post(path: "/books/summarize/stop", body: Data("{}".utf8))
    }

    func startSummarize(bookId: String) async throws {
        _ = try await post(path: "/books/\(bookId)/summarize/start", body: Data("{}".utf8))
    }

    func stopSummarize(bookId: String) async throws {
        _ = try await post(path: "/books/\(bookId)/summarize/stop", body: Data("{}".utf8))
    }

    func retrySegment(bookId: String, idx: Int) async throws {
        _ = try await post(path: "/books/\(bookId)/segments/\(idx)/retry", body: Data("{}".utf8))
    }

    func retrySegments(bookId: String, indices: [Int]) async throws {
        struct Body: Codable { let indices: [Int] }
        let body = try JSONEncoder().encode(Body(indices: indices))
        _ = try await post(path: "/books/\(bookId)/segments/retry", body: body)
    }

    func regenerateBookSummaries(bookId: String) async throws {
        _ = try await post(path: "/books/\(bookId)/summarize/regenerate", body: Data("{}".utf8))
    }

    func chat(bookId: String, message: String, segmentIndex: Int) async throws -> ChatResponse {
        struct Body: Codable { let message: String; let segment_index: Int; let stream: Bool }
        let body = try JSONEncoder().encode(Body(message: message, segment_index: segmentIndex, stream: false))
        let data = try await post(path: "/books/\(bookId)/chat", body: body)
        return try await Self.decode(ChatResponse.self, from: data)
    }

    func chatStream(
        bookId: String,
        message: String,
        segmentIndex: Int,
        quote: String? = nil,
        onToken: @escaping (String) -> Void
    ) async throws -> ChatResponse {
        struct Body: Codable {
            let message: String
            let segment_index: Int
            let stream: Bool
            let quote: String?
        }
        let body = try JSONEncoder().encode(
            Body(message: message, segment_index: segmentIndex, stream: true, quote: quote)
        )
        var request = URLRequest(url: url(path: "/books/\(bookId)/chat"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = body

        let (bytes, resp) = try await session.bytes(for: request)
        try validate(resp: resp, data: Data())

        var final: ChatResponse?
        var tokenBuffer = ""
        let flushThreshold = 32
        for try await line in bytes.lines {
            try Task.checkCancellation()
            guard line.hasPrefix("data: ") else { continue }
            let jsonStr = String(line.dropFirst(6))
            guard let data = jsonStr.data(using: .utf8),
                  let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
            if obj["type"] as? String == "error" {
                let msg = obj["message"] as? String ?? "深聊未完成（模型输出异常或上下文过长），请重试"
                throw NSError(domain: "CoreClient", code: -1, userInfo: [NSLocalizedDescriptionKey: msg])
            }
            if obj["type"] as? String == "token", let token = obj["content"] as? String {
                tokenBuffer += token
                if tokenBuffer.count >= flushThreshold {
                    onToken(tokenBuffer)
                    tokenBuffer = ""
                }
            }
            if obj["type"] as? String == "done" {
                if !tokenBuffer.isEmpty {
                    onToken(tokenBuffer)
                    tokenBuffer = ""
                }
                let answer = obj["answer"] as? String ?? ""
                let citationsData = try JSONSerialization.data(withJSONObject: obj["citations"] ?? [])
                let citations = (try? JSONDecoder().decode([ChatCitation].self, from: citationsData)) ?? []
                final = ChatResponse(answer: answer, citations: citations, web_refs: nil, evidence_sufficient: obj["evidence_sufficient"] as? Bool)
            }
        }
        if !tokenBuffer.isEmpty { onToken(tokenBuffer) }
        guard let final else {
            throw NSError(
                domain: "CoreClient",
                code: -1,
                userInfo: [NSLocalizedDescriptionKey: "深聊未完成（模型输出异常或上下文过长），请重试"]
            )
        }
        return final
    }

    func exportMarkdown(bookId: String, includeNotes: Bool = false) async throws -> String {
        struct Body: Codable { let include_notes: Bool }
        let body = try JSONEncoder().encode(Body(include_notes: includeNotes))
        let data = try await post(path: "/books/\(bookId)/export", body: body)
        guard let text = String(data: data, encoding: .utf8) else { throw URLError(.badServerResponse) }
        return text
    }

    func listNotes(bookId: String? = nil, segmentId: String? = nil) async throws -> [NoteRow] {
        var items: [URLQueryItem] = []
        if let bookId {
            items.append(URLQueryItem(name: "book_id", value: bookId))
        }
        if let segmentId {
            items.append(URLQueryItem(name: "segment_id", value: segmentId))
        }
        let data = try await get(path: "/notes", queryItems: items.isEmpty ? nil : items)
        struct Resp: Codable { let notes: [NoteRow] }
        return try await Self.decode(Resp.self, from: data).notes
    }

    func createNote(
        bookId: String,
        content: String,
        segmentId: String,
        quote: String? = nil,
        type: String = "manual"
    ) async throws -> NoteRow {
        struct Body: Codable {
            let book_id: String
            let content: String
            let segment_id: String
            let quote: String?
            let type: String
        }
        let body = try JSONEncoder().encode(
            Body(book_id: bookId, content: content, segment_id: segmentId, quote: quote, type: type)
        )
        let data = try await post(path: "/notes", body: body)
        return try await Self.decode(NoteRow.self, from: data)
    }

    func deleteNote(id: String) async throws {
        _ = try await delete(path: "/notes/\(id)")
    }

    func deleteNotes(ids: [String]) async throws {
        for id in ids {
            try await deleteNote(id: id)
        }
    }

    func fetchSettings() async throws -> AppSettings {
        let data = try await get(path: "/settings")
        return try await Self.decode(AppSettings.self, from: data)
    }

    func updateSettings(
        targetLanguage: String,
        webSearchProvider: String,
        tavilyAPIKey: String? = nil,
        models: ModelsSettings? = nil
    ) async throws -> AppSettings {
        struct Body: Codable {
            let target_language: String
            let web_search_provider: String
            let tavily_api_key: String?
            let models: ModelsSettings?
        }
        let body = try JSONEncoder().encode(
            Body(
                target_language: targetLanguage,
                web_search_provider: webSearchProvider,
                tavily_api_key: tavilyAPIKey,
                models: models
            )
        )
        let data = try await put(path: "/settings", body: body)
        return try await Self.decode(AppSettings.self, from: data)
    }

    func fetchOllamaStatus(resourceId: String = "ollama") async throws -> OllamaStatus {
        let data = try await get(path: "/settings/ollama/status?resource_id=\(resourceId)")
        return try await Self.decode(OllamaStatus.self, from: data)
    }

    func fetchAllResourceStatus() async throws -> [ResourceStatus] {
        let data = try await get(path: "/settings/resources/status")
        struct Wrapper: Codable { let resources: [ResourceStatus] }
        return try await Self.decode(Wrapper.self, from: data).resources
    }

    func fetchResourceStatus(resourceId: String) async throws -> ResourceStatus {
        let data = try await get(path: "/settings/resources/\(resourceId)/status")
        return try await Self.decode(ResourceStatus.self, from: data)
    }

    func fetchNewsArticle(id: String) async throws -> NewsArticleDetail {
        let data = try await get(path: "/news/articles/\(id)")
        return try await Self.decode(NewsArticleDetail.self, from: data)
    }

    func readNewsArticle(id: String, forceRefetch: Bool = false, skimOnly: Bool = false) async throws -> NewsReadResult {
        struct Body: Codable {
            let force_refetch: Bool
            let skim_only: Bool
        }
        let body = try JSONEncoder().encode(Body(force_refetch: forceRefetch, skim_only: skimOnly))
        let data = try await postLongRunning(path: "/news/articles/\(id)/read", body: body)
        return try await Self.decode(NewsReadResult.self, from: data)
    }

    func newsChatStream(
        articleId: String,
        message: String,
        quote: String? = nil,
        onToken: @escaping (String) -> Void
    ) async throws -> ChatResponse {
        struct Body: Codable {
            let message: String
            let stream: Bool
            let quote: String?
        }
        let body = try JSONEncoder().encode(Body(message: message, stream: true, quote: quote))
        var request = URLRequest(url: url(path: "/news/articles/\(articleId)/chat"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = body

        let (bytes, resp) = try await session.bytes(for: request)
        try validate(resp: resp, data: Data())

        var final: ChatResponse?
        var tokenBuffer = ""
        let flushThreshold = 32
        for try await line in bytes.lines {
            try Task.checkCancellation()
            guard line.hasPrefix("data: ") else { continue }
            let jsonStr = String(line.dropFirst(6))
            guard let data = jsonStr.data(using: .utf8),
                  let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
            if obj["type"] as? String == "error" {
                let msg = obj["message"] as? String ?? "深聊未完成（模型输出异常或上下文过长），请重试"
                throw NSError(domain: "CoreClient", code: -1, userInfo: [NSLocalizedDescriptionKey: msg])
            }
            if obj["type"] as? String == "token", let token = obj["content"] as? String {
                tokenBuffer += token
                if tokenBuffer.count >= flushThreshold {
                    onToken(tokenBuffer)
                    tokenBuffer = ""
                }
            }
            if obj["type"] as? String == "done" {
                if !tokenBuffer.isEmpty {
                    onToken(tokenBuffer)
                    tokenBuffer = ""
                }
                let answer = obj["answer"] as? String ?? ""
                final = ChatResponse(answer: answer, citations: [], web_refs: nil, evidence_sufficient: obj["evidence_sufficient"] as? Bool)
            }
        }
        if !tokenBuffer.isEmpty { onToken(tokenBuffer) }
        guard let final else {
            throw NSError(
                domain: "CoreClient",
                code: -1,
                userInfo: [NSLocalizedDescriptionKey: "深聊未完成（模型输出异常或上下文过长），请重试"]
            )
        }
        return final
    }

    func search(query: String) async throws -> [SearchHit] {
        let data = try await get(
            path: "/search",
            queryItems: [URLQueryItem(name: "q", value: query)]
        )
        struct Resp: Codable { let results: [SearchHit] }
        return try await Self.decode(Resp.self, from: data).results
    }

    func fetchNewsBrief(limit: Int = 25) async throws -> NewsBrief {
        let data = try await get(
            path: "/news/brief",
            queryItems: [URLQueryItem(name: "limit", value: String(limit))]
        )
        return try await Self.decode(NewsBrief.self, from: data)
    }

    func fetchNewsSources() async throws -> [NewsSource] {
        let data = try await get(path: "/news/sources")
        struct Resp: Codable { let sources: [NewsSource] }
        return try await Self.decode(Resp.self, from: data).sources
    }

    func addNewsSource(url: String, title: String = "") async throws -> NewsSource {
        let body = try JSONEncoder().encode(["url": url, "title": title])
        let data = try await post(path: "/news/sources", body: body)
        return try await Self.decode(NewsSource.self, from: data)
    }

    func deleteNewsSource(id: String) async throws {
        _ = try await delete(path: "/news/sources/\(id)")
    }

    func restoreNewsDefaults() async throws -> [NewsSource] {
        let data = try await post(path: "/news/sources/restore-defaults", body: Data("{}".utf8))
        struct Resp: Codable {
            let restored: Int
            let sources: [NewsSource]
        }
        return try await Self.decode(Resp.self, from: data).sources
    }

    func syncNews() async throws -> [[String: Any]] {
        let data = try await post(path: "/news/sync", body: Data("{}".utf8))
        return try await Task.detached {
            guard let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let results = obj["results"] as? [[String: Any]] else {
                throw URLError(.badServerResponse)
            }
            return results
        }.value
    }

    func subscribeEvents(bookId: String, onEvent: @escaping ([String: Any]) -> Void) -> Task<Void, Never> {
        Task {
            var request = URLRequest(url: url(path: "/books/\(bookId)/events"))
            request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
            do {
                let (bytes, _) = try await session.bytes(for: request)
                for try await line in bytes.lines {
                    try Task.checkCancellation()
                    if line.hasPrefix("data: ") {
                        let jsonStr = String(line.dropFirst(6))
                        if let data = jsonStr.data(using: .utf8),
                           let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any] {
                            onEvent(obj)
                        }
                    }
                }
            } catch {
                if error.isCancellation { return }
            }
        }
    }

    private static let maxConnectionAttempts = 5
    private static let connectionRetryDelayNs: UInt64 = 400_000_000

    private static func decode<T: Decodable>(_ type: T.Type, from data: Data) async throws -> T {
        try await Task.detached {
            try JSONDecoder().decode(type, from: data)
        }.value
    }

    private func url(path: String, queryItems: [URLQueryItem]? = nil) -> URL {
        var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false)!
        let basePath = components.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        let cleanPath = path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        if basePath.isEmpty {
            components.path = "/\(cleanPath)"
        } else {
            components.path = "/\(basePath)/\(cleanPath)"
        }
        components.queryItems = queryItems
        return components.url!
    }

    private func get(path: String, queryItems: [URLQueryItem]? = nil) async throws -> Data {
        try await withConnectionRetry {
            let (data, resp) = try await session.data(from: url(path: path, queryItems: queryItems))
            try validate(resp: resp, data: data)
            return data
        }
    }

    private func put(path: String, body: Data) async throws -> Data {
        try await withConnectionRetry {
            var request = URLRequest(url: url(path: path))
            request.httpMethod = "PUT"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = body
            let (data, resp) = try await session.data(for: request)
            try validate(resp: resp, data: data)
            return data
        }
    }

    private func post(path: String, body: Data) async throws -> Data {
        try await withConnectionRetry {
            var request = URLRequest(url: url(path: path))
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = body
            let (data, resp) = try await session.data(for: request)
            try validate(resp: resp, data: data)
            return data
        }
    }

    /// Long-running POST (news read): no connection retry — retries would re-run LLM.
    private func postLongRunning(path: String, body: Data) async throws -> Data {
        var request = URLRequest(url: url(path: path))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        let (data, resp) = try await Self.longSession.data(for: request)
        try validate(resp: resp, data: data)
        return data
    }

    private func patch(path: String, body: Data) async throws -> Data {
        try await withConnectionRetry {
            var request = URLRequest(url: url(path: path))
            request.httpMethod = "PATCH"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = body
            let (data, resp) = try await session.data(for: request)
            try validate(resp: resp, data: data)
            return data
        }
    }

    private func delete(path: String) async throws -> Data {
        try await withConnectionRetry {
            var request = URLRequest(url: url(path: path))
            request.httpMethod = "DELETE"
            let (data, resp) = try await session.data(for: request)
            try validate(resp: resp, data: data)
            return data
        }
    }

    private func withConnectionRetry(_ operation: () async throws -> Data) async throws -> Data {
        var lastError: Error?
        for attempt in 1...Self.maxConnectionAttempts {
            do {
                return try await operation()
            } catch {
                lastError = error
                guard Self.isRetryableConnectionError(error), attempt < Self.maxConnectionAttempts else {
                    throw error
                }
                try? await Task.sleep(nanoseconds: Self.connectionRetryDelayNs)
            }
        }
        throw lastError ?? URLError(.unknown)
    }

    private static func isRetryableConnectionError(_ error: Error) -> Bool {
        let urlError = error as? URLError
            ?? (error as NSError).userInfo[NSUnderlyingErrorKey] as? URLError
        guard let urlError else {
            let ns = error as NSError
            return ns.domain == NSURLErrorDomain && [
                NSURLErrorCannotConnectToHost,
                NSURLErrorNetworkConnectionLost,
                NSURLErrorTimedOut,
                NSURLErrorNotConnectedToInternet,
                NSURLErrorCannotFindHost,
            ].contains(ns.code)
        }
        switch urlError.code {
        case .cannotConnectToHost, .networkConnectionLost, .timedOut,
             .notConnectedToInternet, .cannotFindHost:
            return true
        default:
            return false
        }
    }

    private func validate(resp: URLResponse, data: Data) throws {
        guard let http = resp as? HTTPURLResponse else { return }
        guard (200...299).contains(http.statusCode) else {
            let msg = Self.httpErrorMessage(data: data, statusCode: http.statusCode)
            throw NSError(domain: "CoreClient", code: http.statusCode, userInfo: [NSLocalizedDescriptionKey: msg])
        }
    }

    /// Prefer FastAPI `{"detail": "..."}` over raw JSON body in alerts.
    private static func httpErrorMessage(data: Data, statusCode: Int) -> String {
        if let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            if let detail = obj["detail"] as? String, !detail.isEmpty {
                return detail
            }
            if let detail = obj["detail"] as? [String: Any],
               let title = detail["title"] as? String {
                return title
            }
        }
        return String(data: data, encoding: .utf8) ?? "HTTP \(statusCode)"
    }
}

private let Accept = "Accept"

extension Error {
    var isCancellation: Bool {
        if self is CancellationError { return true }
        if let urlError = self as? URLError, urlError.code == .cancelled { return true }
        return false
    }
}
