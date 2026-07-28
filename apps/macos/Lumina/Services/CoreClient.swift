import Foundation

struct BookSummary: Codable, Identifiable, Hashable {
    let id: String
    let title: String
    let status: String
    let segment_count: Int?
}

struct SegmentRow: Codable, Identifiable, Hashable {
    let id: String
    let idx: Int
    let label: String?
    let chapter: String?
    let summary_status: String
    let summary_json: String?
    let raw_text: String?
    let translation: String?
    let anchor_label: String?
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
    let url: String
    let published_at: String?
}

struct NewsBrief: Codable {
    let date: String
    let count: Int
    let articles: [NewsArticleCard]
}

@MainActor
final class CoreClient: ObservableObject {
    let baseURL: URL
    private let session = URLSession.shared

    init(baseURL: URL) {
        self.baseURL = baseURL
    }

    func listBooks() async throws -> [BookSummary] {
        let data = try await get(path: "/books")
        struct Resp: Codable { let books: [BookSummary] }
        return try JSONDecoder().decode(Resp.self, from: data).books
    }

    func importBook(path: String, overwrite: Bool = false) async throws -> BookSummary {
        struct Body: Codable { let paths: [String]; let overwrite: Bool }
        let body = try JSONEncoder().encode(Body(paths: [path], overwrite: overwrite))
        let data = try await post(path: "/books/import", body: body)
        struct Resp: Codable { let books: [ImportResult] }
        struct ImportResult: Codable { let book_id: String; let title: String; let status: String }
        let resp = try JSONDecoder().decode(Resp.self, from: data)
        guard let first = resp.books.first else { throw URLError(.badServerResponse) }
        return BookSummary(id: first.book_id, title: first.title, status: first.status, segment_count: nil)
    }

    func openBook(id: String) async throws {
        _ = try await post(path: "/books/\(id)/open", body: Data("{}".utf8))
    }

    func listSegments(bookId: String) async throws -> [SegmentRow] {
        let data = try await get(path: "/books/\(bookId)/segments")
        struct Resp: Codable { let segments: [SegmentRow] }
        return try JSONDecoder().decode(Resp.self, from: data).segments
    }

    func getSegment(bookId: String, idx: Int) async throws -> SegmentRow {
        let data = try await get(path: "/books/\(bookId)/segments/\(idx)")
        return try JSONDecoder().decode(SegmentRow.self, from: data)
    }

    func chat(bookId: String, message: String, segmentIndex: Int) async throws -> ChatResponse {
        struct Body: Codable { let message: String; let segment_index: Int; let stream: Bool }
        let body = try JSONEncoder().encode(Body(message: message, segment_index: segmentIndex, stream: false))
        let data = try await post(path: "/books/\(bookId)/chat", body: body)
        return try JSONDecoder().decode(ChatResponse.self, from: data)
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
        var request = URLRequest(url: baseURL.appendingPathComponent("/books/\(bookId)/chat"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = body

        let (bytes, resp) = try await session.bytes(for: request)
        try validate(resp: resp, data: Data())

        var final: ChatResponse?
        for try await line in bytes.lines {
            guard line.hasPrefix("data: ") else { continue }
            let jsonStr = String(line.dropFirst(6))
            guard let data = jsonStr.data(using: .utf8),
                  let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
            if obj["type"] as? String == "token", let token = obj["content"] as? String {
                onToken(token)
            }
            if obj["type"] as? String == "done" {
                let answer = obj["answer"] as? String ?? ""
                let citationsData = try JSONSerialization.data(withJSONObject: obj["citations"] ?? [])
                let citations = try JSONDecoder().decode([ChatCitation].self, from: citationsData)
                final = ChatResponse(answer: answer, citations: citations, web_refs: nil, evidence_sufficient: obj["evidence_sufficient"] as? Bool)
            }
        }
        guard let final else { throw URLError(.badServerResponse) }
        return final
    }

    func exportMarkdown(bookId: String, includeNotes: Bool = false) async throws -> String {
        struct Body: Codable { let include_notes: Bool }
        let body = try JSONEncoder().encode(Body(include_notes: includeNotes))
        let data = try await post(path: "/books/\(bookId)/export", body: body)
        guard let text = String(data: data, encoding: .utf8) else { throw URLError(.badServerResponse) }
        return text
    }

    func listNotes(bookId: String) async throws -> [NoteRow] {
        let data = try await get(path: "/notes?book_id=\(bookId)")
        struct Resp: Codable { let notes: [NoteRow] }
        return try JSONDecoder().decode(Resp.self, from: data).notes
    }

    func createNote(
        bookId: String,
        content: String,
        segmentId: String? = nil,
        quote: String? = nil,
        type: String = "manual"
    ) async throws -> NoteRow {
        struct Body: Codable {
            let book_id: String
            let content: String
            let segment_id: String?
            let quote: String?
            let type: String
        }
        let body = try JSONEncoder().encode(
            Body(book_id: bookId, content: content, segment_id: segmentId, quote: quote, type: type)
        )
        let data = try await post(path: "/notes", body: body)
        return try JSONDecoder().decode(NoteRow.self, from: data)
    }

    func fetchSettings() async throws -> AppSettings {
        let data = try await get(path: "/settings")
        return try JSONDecoder().decode(AppSettings.self, from: data)
    }

    func updateSettings(targetLanguage: String, webSearchEnabled: Bool) async throws -> AppSettings {
        struct Body: Codable {
            let target_language: String
            let web_search_enabled: Bool
        }
        let body = try JSONEncoder().encode(Body(target_language: targetLanguage, web_search_enabled: webSearchEnabled))
        let data = try await put(path: "/settings", body: body)
        return try JSONDecoder().decode(AppSettings.self, from: data)
    }

    func fetchOllamaStatus() async throws -> OllamaStatus {
        let data = try await get(path: "/settings/ollama/status")
        return try JSONDecoder().decode(OllamaStatus.self, from: data)
    }

    func fetchNewsArticle(id: String) async throws -> NewsArticleDetail {
        let data = try await get(path: "/news/articles/\(id)")
        return try JSONDecoder().decode(NewsArticleDetail.self, from: data)
    }

    func newsChatStream(
        articleId: String,
        message: String,
        onToken: @escaping (String) -> Void
    ) async throws -> ChatResponse {
        struct Body: Codable { let message: String; let stream: Bool }
        let body = try JSONEncoder().encode(Body(message: message, stream: true))
        var request = URLRequest(url: baseURL.appendingPathComponent("/news/articles/\(articleId)/chat"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = body

        let (bytes, resp) = try await session.bytes(for: request)
        try validate(resp: resp, data: Data())

        var final: ChatResponse?
        for try await line in bytes.lines {
            guard line.hasPrefix("data: ") else { continue }
            let jsonStr = String(line.dropFirst(6))
            guard let data = jsonStr.data(using: .utf8),
                  let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
            if obj["type"] as? String == "token", let token = obj["content"] as? String {
                onToken(token)
            }
            if obj["type"] as? String == "done" {
                let answer = obj["answer"] as? String ?? ""
                final = ChatResponse(answer: answer, citations: [], web_refs: nil, evidence_sufficient: obj["evidence_sufficient"] as? Bool)
            }
        }
        guard let final else { throw URLError(.badServerResponse) }
        return final
    }

    func search(query: String) async throws -> [SearchHit] {
        let encoded = query.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? query
        let data = try await get(path: "/search?q=\(encoded)")
        struct Resp: Codable { let results: [SearchHit] }
        return try JSONDecoder().decode(Resp.self, from: data).results
    }

    func fetchNewsBrief() async throws -> NewsBrief {
        let data = try await get(path: "/news/brief")
        return try JSONDecoder().decode(NewsBrief.self, from: data)
    }

    func syncNews() async throws -> [[String: Any]] {
        let data = try await post(path: "/news/sync", body: Data("{}".utf8))
        guard let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let results = obj["results"] as? [[String: Any]] else {
            throw URLError(.badServerResponse)
        }
        return results
    }

    func subscribeEvents(bookId: String, onEvent: @escaping ([String: Any]) -> Void) -> Task<Void, Never> {
        Task {
            var request = URLRequest(url: baseURL.appendingPathComponent("/books/\(bookId)/events"))
            request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
            do {
                let (bytes, _) = try await session.bytes(for: request)
                for try await line in bytes.lines {
                    if line.hasPrefix("data: ") {
                        let jsonStr = String(line.dropFirst(6))
                        if let data = jsonStr.data(using: .utf8),
                           let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any] {
                            onEvent(obj)
                        }
                    }
                }
            } catch { }
        }
    }

    private func get(path: String) async throws -> Data {
        let (data, resp) = try await session.data(from: baseURL.appendingPathComponent(path))
        try validate(resp: resp, data: data)
        return data
    }

    private func put(path: String, body: Data) async throws -> Data {
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.httpMethod = "PUT"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        let (data, resp) = try await session.data(for: request)
        try validate(resp: resp, data: data)
        return data
    }

    private func post(path: String, body: Data) async throws -> Data {
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        let (data, resp) = try await session.data(for: request)
        try validate(resp: resp, data: data)
        return data
    }

    private func validate(resp: URLResponse, data: Data) throws {
        guard let http = resp as? HTTPURLResponse else { return }
        guard (200...299).contains(http.statusCode) else {
            let msg = String(data: data, encoding: .utf8) ?? "HTTP \(http.statusCode)"
            throw NSError(domain: "CoreClient", code: http.statusCode, userInfo: [NSLocalizedDescriptionKey: msg])
        }
    }
}

private let Accept = "Accept"
