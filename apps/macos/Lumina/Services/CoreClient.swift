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
    var chunk_target_chars: Int?
    var summary_ready_count: Int?
    var summary_total_count: Int?
    var chunker_version: String?
    var language: String?
    var target_language: String?
    var summarize_active: SummarizeActive?
    var summarize_state: String?
    var summarize_queued_count: Int?
    var summary_tier: String?
    var processing_kind: String?
    var index_status: String?
    var ingest_error: String?
    /// Local overlay only — not decoded from the API.
    var readingPercent: Double? = nil

    enum CodingKeys: String, CodingKey {
        case id, title, status, segment_count, is_favorite, category
        case last_opened_at, current_segment_index, author, created_at
        case total_char_count, chunk_target_chars, summary_ready_count, summary_total_count, chunker_version
        case language, target_language, summarize_active, summarize_state
        case summarize_queued_count, summary_tier, processing_kind, index_status, ingest_error
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
        chunk_target_chars: Int? = nil,
        summary_ready_count: Int? = nil,
        summary_total_count: Int? = nil,
        chunker_version: String? = nil,
        language: String? = nil,
        target_language: String? = nil,
        summarize_active: SummarizeActive? = nil,
        summarize_state: String? = nil,
        summarize_queued_count: Int? = nil,
        summary_tier: String? = nil,
        processing_kind: String? = nil,
        index_status: String? = nil,
        ingest_error: String? = nil,
        readingPercent: Double? = nil
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
        self.chunk_target_chars = chunk_target_chars
        self.summary_ready_count = summary_ready_count
        self.summary_total_count = summary_total_count
        self.chunker_version = chunker_version
        self.language = language
        self.target_language = target_language
        self.summarize_active = summarize_active
        self.summarize_state = summarize_state
        self.summarize_queued_count = summarize_queued_count
        self.summary_tier = summary_tier
        self.processing_kind = processing_kind
        self.index_status = index_status
        self.ingest_error = ingest_error
        self.readingPercent = readingPercent
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
        chunk_target_chars = try c.decodeIfPresent(Int.self, forKey: .chunk_target_chars)
        summary_ready_count = try c.decodeIfPresent(Int.self, forKey: .summary_ready_count)
        summary_total_count = try c.decodeIfPresent(Int.self, forKey: .summary_total_count)
        chunker_version = try c.decodeIfPresent(String.self, forKey: .chunker_version)
        language = try c.decodeIfPresent(String.self, forKey: .language)
        target_language = try c.decodeIfPresent(String.self, forKey: .target_language)
        summarize_active = try c.decodeIfPresent(SummarizeActive.self, forKey: .summarize_active)
        summarize_state = try c.decodeIfPresent(String.self, forKey: .summarize_state)
        summarize_queued_count = try c.decodeIfPresent(Int.self, forKey: .summarize_queued_count)
        summary_tier = try c.decodeIfPresent(String.self, forKey: .summary_tier)
        processing_kind = try c.decodeIfPresent(String.self, forKey: .processing_kind)
        index_status = try c.decodeIfPresent(String.self, forKey: .index_status)
        ingest_error = try c.decodeIfPresent(String.self, forKey: .ingest_error)
        readingPercent = nil
    }

    var canChatBook: Bool {
        hasCompletedSummary && (index_status ?? "idle") == "ready"
    }

    var bookIndexLabel: String {
        switch index_status {
        case "building": return "全书（索引生成中）"
        case "error": return "全书（索引失败）"
        case "ready": return "全书"
        default: return hasCompletedSummary ? "全书（索引生成中）" : "全书"
        }
    }

    var isFavorite: Bool { is_favorite ?? false }

    var summaryTotal: Int { summary_total_count ?? segment_count ?? 0 }

    var summaryReady: Int { summary_ready_count ?? 0 }

    var hasCompletedSummary: Bool {
        summaryTotal > 0 && summaryReady >= summaryTotal
    }

    var readingTotal: Int {
        max(segment_count ?? 0, 0)
    }

    var readingCurrent: Int {
        guard last_opened_at != nil, readingTotal > 0 else { return 0 }
        let index = min(max(current_segment_index ?? 0, 0), readingTotal - 1)
        return index + 1
    }

    var readingStatusLabel: String {
        ReadingProgress.statusLabel(
            opened: last_opened_at != nil,
            index: current_segment_index ?? 0,
            segmentCount: readingTotal
        )
    }

    var resolvedReadingPercent: Double {
        if let readingPercent { return readingPercent }
        return ReadingProgress.percent(
            index: current_segment_index ?? 0,
            count: readingTotal
        )
    }

    var readingProgressBucket: ReadingProgressBucket {
        guard last_opened_at != nil else { return .unread }
        guard readingTotal > 0 else { return .reading }
        return ReadingProgress.isFinished(
            index: current_segment_index ?? 0,
            count: readingTotal
        ) ? .finished : .reading
    }

    var segmentCountLabel: String {
        let count = segment_count ?? 0
        return count > 0 ? "\(count) 段" : "未分段"
    }

    var coverInitial: String {
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let first = trimmed.first else { return "书" }
        return String(first)
    }

    var progressLabel: String {
        let total = summaryTotal
        if status == "processing" { return statusLabel }
        guard total > 0 else { return statusLabel }
        let ready = summaryReady
        if ready >= total { return readingStatusLabel }
        var label = "\(statusLabel) · 摘要 \(ready)/\(total)"
        if let active = summarize_active,
           let activeLabel = SummaryMetricsFormatter.bookActiveLabel(active: active) {
            label += " · \(activeLabel)"
        }
        return label
    }

    var isProcessing: Bool { status == "processing" }

    var summarizeQueuedCount: Int { summarize_queued_count ?? 0 }

    var canStartSummarize: Bool {
        guard !isProcessing, summaryTotal > 0, summaryReady < summaryTotal else { return false }
        switch summarize_state {
        case "idle", "paused": return true
        default: return false
        }
    }

    var canStopSummarize: Bool {
        guard !isProcessing else { return false }
        switch summarize_state {
        case "running", "queued", "paused": return true
        default: return false
        }
    }

    /// Ready books can be re-chunked from the library or reader. Import
    /// failures and in-flight ingest/resegment jobs cannot.
    var canResegment: Bool {
        !isProcessing && status != "error" && (segment_count ?? 0) > 0
    }

    var statusLabel: String {
        switch status {
        case "unread": return "未读"
        case "reading": return "在读"
        case "summarized": return "已摘要"
        case "processing": return "处理中"
        case "error":
            if let reason = ingest_error?.trimmingCharacters(in: .whitespacesAndNewlines),
               !reason.isEmpty {
                return "导入失败：\(reason)"
            }
            return "导入失败"
        default: return status
        }
    }
}

struct SummarizeOverview: Codable {
    struct Counts: Codable {
        let running: Int
        let queued: Int
        let paused: Int
        let idle: Int
        let summarized: Int
        /// Books whose whole-book index is being built right now.
        let indexing: Int?
    }

    let counts: Counts
    let user_paused_all: Bool
    let indexing_queued: Int?
    /// Why nothing is in progress while work is queued. Nil when not stalled.
    let stalled_reason: String?

    var indexingCount: Int { counts.indexing ?? 0 }

    var activeCount: Int { counts.running + counts.queued + indexingCount }
}

enum ReadingProgressBucket: String {
    case unread, reading, finished
}

enum SummarizeStateFilter: String, CaseIterable, Identifiable {
    case all, running, idle, summarized

    var id: String { rawValue }

    var label: String {
        switch self {
        case .all: return "全部"
        case .running: return "正在摘要"
        case .idle: return "待摘要"
        case .summarized: return "已摘要"
        }
    }

    var systemImage: String {
        switch self {
        case .all: return "square.stack.3d.up"
        case .running: return "arrow.triangle.2.circlepath"
        case .idle: return "doc.text"
        case .summarized: return "checkmark.circle"
        }
    }

    func matches(_ book: BookSummary) -> Bool {
        switch self {
        case .all:
            return true
        case .running:
            return book.summarize_state == "running" || book.summarize_state == "queued"
        case .idle:
            return book.summarize_state == "idle" || book.summarize_state == "paused"
        case .summarized:
            return book.summarize_state == "summarized"
                || (book.summaryTotal > 0 && book.summaryReady >= book.summaryTotal)
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

struct LibraryFilter: Hashable, Identifiable {
    let rawValue: String

    static let all = LibraryFilter(rawValue: "all")
    static let summarized = LibraryFilter(rawValue: "summarized")

    static let fallbackCategories = ["文学", "历史", "科技", "哲学", "经济", "传记", "其他"]

    var id: String { rawValue }

    var label: String {
        switch rawValue {
        case "all": return "全部"
        case "summarized": return "已摘要"
        default: return rawValue
        }
    }

    var systemImage: String {
        switch rawValue {
        case "all": return "books.vertical"
        case "文学": return "book"
        case "历史": return "clock.arrow.circlepath"
        case "科技": return "cpu"
        case "哲学": return "brain.head.profile"
        case "经济": return "chart.line.uptrend.xyaxis"
        case "传记": return "person.text.rectangle"
        case "其他": return "ellipsis.circle"
        default: return "tag"
        }
    }

    var queryValue: String { rawValue }

    static func category(_ name: String) -> LibraryFilter {
        LibraryFilter(rawValue: name)
    }

    static func standardFilters(categories: [String]) -> [LibraryFilter] {
        [.all] + categories.map { category($0) }
    }

    init(rawValue: String) {
        self.rawValue = rawValue
    }

    /// Migrate legacy collection preferences (all → recent; unread/reading restored).
    static func fromPersisted(_ raw: String) -> LibraryFilter {
        switch raw {
        case "all", "recent": return .all
        case "summarized": return .summarized
        case "unread", "reading", "finished", "idle", "summarizing", "favorite":
            return LibraryFilter(rawValue: raw)
        default:
            if fallbackCategories.contains(raw) {
                return category(raw)
            }
            return .all
        }
    }
}

enum LibraryCollection: Hashable, Identifiable {
    case recent
    case idle
    case summarizing
    case summarized
    case unread
    case reading
    case finished
    case favorite
    case category(String)

    var id: String { rawValue }

    var rawValue: String {
        switch self {
        case .recent: return "recent"
        case .idle: return "idle"
        case .summarizing: return "summarizing"
        case .summarized: return "summarized"
        case .unread: return "unread"
        case .reading: return "reading"
        case .finished: return "finished"
        case .favorite: return "favorite"
        case .category(let name): return name
        }
    }

    var label: String {
        switch self {
        case .recent: return "最近"
        case .idle: return "未摘要"
        case .summarizing: return "摘要中"
        case .summarized: return "已摘要"
        case .unread: return "未读"
        case .reading: return "在读"
        case .finished: return "已读完"
        case .favorite: return "收藏"
        case .category(let name): return name
        }
    }

    var systemImage: String {
        switch self {
        case .recent: return "clock"
        case .idle: return "doc.text"
        case .summarizing: return "arrow.triangle.2.circlepath"
        case .summarized: return "checkmark.circle"
        case .unread: return "book.closed"
        case .reading: return "book"
        case .finished: return "checkmark.circle.fill"
        case .favorite: return "star.fill"
        case .category(let name):
            return LibraryFilter.category(name).systemImage
        }
    }

    var section: LibraryCollectionSection {
        switch self {
        case .recent: return .defaultSection
        case .idle, .summarizing, .summarized: return .summary
        case .unread, .reading, .finished: return .reading
        case .favorite: return .favorite
        case .category: return .category
        }
    }

    func matches(_ book: BookSummary) -> Bool {
        switch self {
        case .recent:
            return true
        case .idle:
            return book.summarize_state == "idle" || book.summarize_state == "paused"
        case .summarizing:
            return book.summarize_state == "running" || book.summarize_state == "queued"
        case .summarized:
            return book.summarize_state == "summarized"
                || (book.summaryTotal > 0 && book.summaryReady >= book.summaryTotal)
        case .unread:
            return book.readingProgressBucket == .unread
        case .reading:
            return book.readingProgressBucket == .reading
        case .finished:
            return book.readingProgressBucket == .finished
        case .favorite:
            return book.isFavorite
        case .category(let name):
            return book.category == name
        }
    }

    static func fromPersisted(_ raw: String) -> LibraryCollection {
        switch raw {
        case "all", "recent": return .recent
        case "idle": return .idle
        case "summarizing", "running": return .summarizing
        case "summarized": return .summarized
        case "unread": return .unread
        case "reading": return .reading
        case "finished": return .finished
        case "favorite": return .favorite
        default:
            if LibraryFilter.fallbackCategories.contains(raw) {
                return .category(raw)
            }
            return .recent
        }
    }

    static func sidebarItems(categories: [String]) -> [LibraryCollection] {
        let cats = categories.isEmpty ? LibraryFilter.fallbackCategories : categories
        return [
            .recent,
            .idle, .summarizing, .summarized,
            .unread, .reading, .finished,
            .favorite,
        ] + cats.map { .category($0) }
    }
}

enum LibraryCollectionSection: String, CaseIterable, Identifiable {
    case defaultSection
    case summary
    case reading
    case favorite
    case category

    var id: String { rawValue }

    var label: String? {
        switch self {
        case .defaultSection: return nil
        case .summary: return "摘要"
        case .reading: return "阅读"
        case .favorite: return nil
        case .category: return "分类"
        }
    }
}

enum LibrarySort: String, CaseIterable, Identifiable {
    case recent, added, title, segments, favorite

    var id: String { rawValue }

    var label: String {
        switch self {
        case .recent: return "最近访问"
        case .added: return "添加时间"
        case .title: return "标题"
        case .segments: return "段落数"
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
    var chapter: String?
    var summary_status: String
    var summary_json: String?
    let raw_text: String?
    var translation: String?
    var anchor_label: String?
    var summary_provider: String?
    var summary_model: String?
    var summary_tier: String?
    var char_count: Int?
    var retry_count: Int?
    var summary_duration_s: Double?
    var summary_llm_attempts: Int?
}

struct SegmentBoundaryCandidate: Codable, Hashable {
    let offset: Int
    let kind: String
}

struct SegmentBoundaryPreview: Codable {
    let left_idx: Int
    let right_idx: Int
    let total_chars: Int
    let left_char_count: Int
    let candidates: [SegmentBoundaryCandidate]
    let oversized_limit: Int
}

struct SegmentBoundaryMoveResult: Codable {
    let left_idx: Int
    let right_idx: Int
    let left_char_count: Int
    let right_char_count: Int
    let left_anchor_label: String?
    let right_anchor_label: String?
    let left_chapter: String?
    let right_chapter: String?
    let left_page_range: String?
    let right_page_range: String?
    let left_status: String?
    let right_status: String?
    let oversized: Bool
    let unchanged: Bool
    let oversized_limit: Int?
}

struct SegmentSummaryDetail: Codable {
    let idx: Int
    var summary_json: String?
    var label: String?
    var anchor_label: String?
    var summary_status: String?
    var summary_provider: String?
    var summary_model: String?
    var summary_tier: String?
    var summary_duration_s: Double?
    var summary_llm_attempts: Int?
}

enum SummaryTier: String, Codable, CaseIterable, Identifiable {
    case normal
    case advanced

    var id: String { rawValue }
    var label: String { self == .normal ? "正常摘要" : "高级摘要" }
    /// Start/resume: only incomplete segments; does not overwrite ready summaries.
    var startMenuLabel: String {
        self == .normal ? "正常摘要" : "高级摘要（仅未摘要）"
    }
    /// Whole-book regenerate: overwrites every segment.
    var regenerateMenuLabel: String {
        self == .normal ? "正常摘要（覆盖全书）" : "高级摘要（覆盖全书）"
    }
}

struct ChatCitation: Codable {
    let segment_index: Int
    let label: String
}

struct ChatWebRef: Identifiable, Hashable {
    let title: String
    let url: String
    let source: String?

    var id: String { url }

    var displayLabel: String {
        let name = title.isEmpty ? url : title
        if let source, !source.isEmpty {
            return "[网] \(name) · \(source)"
        }
        return "[网] \(name)"
    }
}

struct ChatResponse: Codable {
    let answer: String
    let citations: [ChatCitation]
    let web_refs: [[String: String]]?
    let evidence_sufficient: Bool?
    let provider: String?
    let model: String?
    let duration_ms: Int?
    let prompt_tokens: Int?
    let completion_tokens: Int?
    let total_tokens: Int?
    let tps: Double?

    init(
        answer: String,
        citations: [ChatCitation],
        web_refs: [[String: String]]? = nil,
        evidence_sufficient: Bool? = nil,
        provider: String? = nil,
        model: String? = nil,
        duration_ms: Int? = nil,
        prompt_tokens: Int? = nil,
        completion_tokens: Int? = nil,
        total_tokens: Int? = nil,
        tps: Double? = nil
    ) {
        self.answer = answer
        self.citations = citations
        self.web_refs = web_refs
        self.evidence_sufficient = evidence_sufficient
        self.provider = provider
        self.model = model
        self.duration_ms = duration_ms
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens
        self.tps = tps
    }

    static func fromSSEDone(_ obj: [String: Any], citations: [ChatCitation]) -> ChatResponse {
        ChatResponse(
            answer: obj["answer"] as? String ?? "",
            citations: citations,
            web_refs: parseWebRefDicts(obj["web_refs"]),
            evidence_sufficient: obj["evidence_sufficient"] as? Bool,
            provider: obj["provider"] as? String,
            model: obj["model"] as? String,
            duration_ms: Self.intValue(obj["duration_ms"]),
            prompt_tokens: Self.intValue(obj["prompt_tokens"]),
            completion_tokens: Self.intValue(obj["completion_tokens"]),
            total_tokens: Self.intValue(obj["total_tokens"]),
            tps: Self.doubleValue(obj["tps"])
        )
    }

    var webRefs: [ChatWebRef] {
        Self.parseWebRefs(web_refs)
    }

    static func parseWebRefDicts(_ value: Any?) -> [[String: String]]? {
        guard let items = value as? [Any] else { return nil }
        var out: [[String: String]] = []
        for item in items {
            guard let dict = item as? [String: Any] else { continue }
            let url = dict["url"] as? String ?? ""
            if url.isEmpty { continue }
            var row: [String: String] = ["url": url]
            if let title = dict["title"] as? String { row["title"] = title }
            if let source = dict["source"] as? String { row["source"] = source }
            out.append(row)
        }
        return out.isEmpty ? nil : out
    }

    static func parseWebRefs(_ dicts: [[String: String]]?) -> [ChatWebRef] {
        (dicts ?? []).compactMap { row in
            let url = row["url"] ?? ""
            guard !url.isEmpty else { return nil }
            return ChatWebRef(title: row["title"] ?? "", url: url, source: row["source"])
        }
    }

    private static func intValue(_ value: Any?) -> Int? {
        if let n = value as? Int { return n }
        if let n = value as? Double { return Int(n) }
        return nil
    }

    private static func doubleValue(_ value: Any?) -> Double? {
        if let n = value as? Double { return n }
        if let n = value as? Int { return Double(n) }
        return nil
    }
}

struct ChatMessage: Identifiable {
    let id: UUID
    let role: String
    var content: String
    var citations: [ChatCitation]
    var webRefs: [ChatWebRef]
    var provider: String?
    var model: String?
    var duration_ms: Int?
    var prompt_tokens: Int?
    var completion_tokens: Int?
    var total_tokens: Int?
    var tps: Double?

    init(
        role: String,
        content: String,
        citations: [ChatCitation] = [],
        webRefs: [ChatWebRef] = [],
        provider: String? = nil,
        model: String? = nil,
        duration_ms: Int? = nil,
        prompt_tokens: Int? = nil,
        completion_tokens: Int? = nil,
        total_tokens: Int? = nil,
        tps: Double? = nil
    ) {
        self.id = UUID()
        self.role = role
        self.content = content
        self.citations = citations
        self.webRefs = webRefs
        self.provider = provider
        self.model = model
        self.duration_ms = duration_ms
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens
        self.tps = tps
    }

    mutating func applyMetrics(from resp: ChatResponse) {
        provider = resp.provider
        model = resp.model
        duration_ms = resp.duration_ms
        prompt_tokens = resp.prompt_tokens
        completion_tokens = resp.completion_tokens
        total_tokens = resp.total_tokens
        tps = resp.tps
        webRefs = resp.webRefs
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

struct ContextProbeStep: Codable, Equatable {
    let chars: Int
    let ok: Bool
    let message: String?
}

struct ContextProbeStatus: Codable, Equatable {
    let resource_id: String
    let status: String
    let model: String?
    let current_chars: Int?
    let max_ok_chars: Int?
    let recommended_chars: Int?
    let steps: [ContextProbeStep]?
    let message: String?
    let waiting_for_slot: Bool?

    var isRunning: Bool { status == "running" }

    var displayMessage: String {
        let trimmed = message?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !trimmed.isEmpty { return trimmed }
        switch status {
        case "running": return "正在测试后面的段是否仍被理解…"
        case "done": return "测试完成"
        case "cancelled": return "已取消"
        case "failed": return "测试失败"
        default: return ""
        }
    }
}

struct OcrStatus: Codable {
    let provider: String
    let ready: Bool
    let probe_ok: Bool
    let configured: Bool
    let key_configured: Bool
    let model_ready: Bool
    let message: String?
    let base_url: String?

    var displayMessage: String {
        let trimmed = message?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return trimmed.isEmpty ? (ready ? "已就绪" : "未就绪") : trimmed
    }
}

// MARK: - Ops / DEBUG task management

struct OpsTaskCounts: Codable {
    let queued: Int
    let running: Int
    let paused: Int?
    let completed: Int
    let failed: Int
    let cancelled: Int
}

struct OpsJobQueueDiagnostics: Codable {
    let queue_depth: Int
    let active_jobs: [OpsActiveJob]
    let paused_backlog_depth: Int?
    let worker_count: Int
    let worker_target: Int
    let chat_preempted: Bool
    let user_paused_all: Bool
    let user_paused_books: [String]
}

struct OpsActiveJob: Codable, Identifiable {
    var id: String { job_key ?? "\(book_id)-\(segment_idx)-\(kind)" }
    let book_id: String
    let segment_idx: Int
    let kind: String
    let job_key: String?
}

struct OpsLastCall: Codable {
    let resource_id: String?
    let profile: String?
    let started_at: String?
    let duration_ms: Int?
    let ok: Bool?
    let error: String?
}

struct OpsOverview: Codable {
    let task_counts: OpsTaskCounts
    let job_queue: OpsJobQueueDiagnostics
    let resource_runtime: [ResourceRuntimeRow]
    let last_call: OpsLastCall?
}

struct OpsTask: Codable, Identifiable {
    let id: String
    let kind: String
    let status: String
    let subject_type: String
    let subject_id: String
    let subject_label: String
    let detail: String
    let resource_id: String?
    let profile: String?
    let started_at: String
    let updated_at: String
    let error: String?
    let cancellable: Bool
    let job_key: String?
    let llm_attempt: Int?
    let max_llm_attempts: Int?
    let duration_s: Double?
}

struct OpsTasksResponse: Codable {
    let tasks: [OpsTask]
    let counts: OpsTaskCounts
}

struct ResourceRuntimeRow: Codable, Identifiable {
    var id: String { resource_id }
    let resource_id: String
    let limit: Int
    let in_use: Int
    let available: Int
    let probe: ResourceStatus?
}

struct ResourceRuntimeResponse: Codable {
    let resources: [ResourceRuntimeRow]
    let last_call: OpsLastCall?
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
        filter: LibraryFilter = .all,
        sort: LibrarySort = .recent
    ) async throws -> [BookSummary] {
        let data = try await get(path: "/books", queryItems: [
            URLQueryItem(name: "filter", value: filter.queryValue),
            URLQueryItem(name: "sort", value: sort.queryValue),
        ])
        struct Resp: Codable { let books: [BookSummary] }
        return try await Self.decode(Resp.self, from: data).books
    }

    func listBookCategories() async throws -> [String] {
        let data = try await get(path: "/books/categories")
        struct Resp: Codable { let categories: [String] }
        return try await Self.decode(Resp.self, from: data).categories
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
        let data = try await getLongRunning(path: "/books/\(bookId)/segments")
        struct Resp: Codable { let segments: [SegmentRow] }
        return try await Self.decode(Resp.self, from: data).segments
    }

    func getSegment(bookId: String, idx: Int) async throws -> SegmentRow {
        let data = try await get(path: "/books/\(bookId)/segments/\(idx)")
        return try await Self.decode(SegmentRow.self, from: data)
    }

    func fetchSegmentBoundary(bookId: String, idx: Int) async throws -> SegmentBoundaryPreview {
        let data = try await get(path: "/books/\(bookId)/segments/\(idx)/boundary")
        return try await Self.decode(SegmentBoundaryPreview.self, from: data)
    }

    func moveSegmentBoundary(
        bookId: String, idx: Int, leftCharCount: Int
    ) async throws -> SegmentBoundaryMoveResult {
        struct Body: Codable { let left_char_count: Int }
        let body = try JSONEncoder().encode(Body(left_char_count: leftCharCount))
        let data = try await post(path: "/books/\(bookId)/segments/\(idx)/boundary", body: body)
        return try await Self.decode(SegmentBoundaryMoveResult.self, from: data)
    }

    func fetchSegmentSummary(bookId: String, idx: Int) async throws -> SegmentSummaryDetail {
        let data = try await get(path: "/books/\(bookId)/segments/\(idx)/summary")
        return try await Self.decode(SegmentSummaryDetail.self, from: data)
    }

    func startSummarizeAll(summaryTier: SummaryTier = .normal) async throws {
        struct Body: Codable { let summary_tier: SummaryTier }
        let body = try JSONEncoder().encode(Body(summary_tier: summaryTier))
        _ = try await post(path: "/books/summarize/start", body: body)
    }

    func stopSummarizeAll() async throws {
        _ = try await post(path: "/books/summarize/stop", body: Data("{}".utf8))
    }

    func startSummarize(bookIds: [String], summaryTier: SummaryTier = .normal) async throws {
        struct Body: Codable {
            let book_ids: [String]
            let summary_tier: SummaryTier
        }
        let body = try JSONEncoder().encode(
            Body(book_ids: bookIds, summary_tier: summaryTier)
        )
        _ = try await post(path: "/books/summarize/start", body: body)
    }

    func stopSummarize(bookIds: [String]) async throws {
        struct Body: Codable { let book_ids: [String] }
        let body = try JSONEncoder().encode(Body(book_ids: bookIds))
        _ = try await post(path: "/books/summarize/stop", body: body)
    }

    func fetchSummarizeOverview() async throws -> SummarizeOverview {
        let data = try await get(path: "/books/summarize/overview")
        return try await Self.decode(SummarizeOverview.self, from: data)
    }

    func startSummarize(bookId: String, summaryTier: SummaryTier = .normal) async throws {
        struct Body: Codable { let summary_tier: SummaryTier }
        let body = try JSONEncoder().encode(Body(summary_tier: summaryTier))
        _ = try await post(path: "/books/\(bookId)/summarize/start", body: body)
    }

    func stopSummarize(bookId: String) async throws {
        _ = try await post(path: "/books/\(bookId)/summarize/stop", body: Data("{}".utf8))
    }

    /// Queue the whole-book index. Nothing builds it automatically.
    func buildBookIndex(bookId: String) async throws {
        _ = try await post(path: "/books/\(bookId)/index", body: Data("{}".utf8))
    }

    func retrySegment(bookId: String, idx: Int, summaryTier: SummaryTier? = nil) async throws {
        struct Body: Codable { let summary_tier: SummaryTier? }
        let body = try JSONEncoder().encode(Body(summary_tier: summaryTier))
        _ = try await post(path: "/books/\(bookId)/segments/\(idx)/retry", body: body)
    }

    func retrySegments(bookId: String, indices: [Int], summaryTier: SummaryTier? = nil) async throws {
        struct Body: Codable {
            let indices: [Int]
            let summary_tier: SummaryTier?
        }
        let body = try JSONEncoder().encode(
            Body(indices: indices, summary_tier: summaryTier)
        )
        _ = try await post(path: "/books/\(bookId)/segments/retry", body: body)
    }

    func regenerateBookSummaries(bookId: String, summaryTier: SummaryTier = .normal) async throws {
        struct Body: Codable { let summary_tier: SummaryTier }
        let body = try JSONEncoder().encode(Body(summary_tier: summaryTier))
        _ = try await post(path: "/books/\(bookId)/summarize/regenerate", body: body)
    }

    func resegmentBook(bookId: String, chunkTargetChars: Int) async throws {
        struct Body: Codable { let chunk_target_chars: Int }
        let body = try JSONEncoder().encode(Body(chunk_target_chars: chunkTargetChars))
        _ = try await post(path: "/books/\(bookId)/resegment", body: body)
    }

    func cancelResegmentBook(bookId: String) async throws {
        _ = try await post(path: "/books/\(bookId)/resegment/cancel", body: Data("{}".utf8))
    }

    func cancelIngestBook(bookId: String) async throws {
        _ = try await post(path: "/books/\(bookId)/ingest/cancel", body: Data("{}".utf8))
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
        scope: String = "segment",
        onStatus: ((String) -> Void)? = nil,
        onToken: @escaping (String) -> Void
    ) async throws -> ChatResponse {
        struct Body: Codable {
            let message: String
            let segment_index: Int
            let stream: Bool
            let quote: String?
            let scope: String
        }
        let body = try JSONEncoder().encode(
            Body(message: message, segment_index: segmentIndex, stream: true, quote: quote, scope: scope)
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
            if obj["type"] as? String == "status", let status = obj["message"] as? String {
                onStatus?(status)
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
                let citationsData = try JSONSerialization.data(withJSONObject: obj["citations"] ?? [])
                let citations = (try? JSONDecoder().decode([ChatCitation].self, from: citationsData)) ?? []
                final = ChatResponse.fromSSEDone(obj, citations: citations)
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
        webSearchEnabled: Bool = true,
        tavilyAPIKey: String? = nil,
        ocrCloudBaseURL: String? = nil,
        ocrCloudModel: String? = nil,
        ocrCloudAPIKey: String? = nil,
        ocrCloudTimeoutSeconds: Double? = nil,
        debugMode: Bool? = nil,
        autoStartSummary: Bool? = nil,
        models: ModelsSettings? = nil,
        prompts: PromptsSettings? = nil
    ) async throws -> AppSettings {
        struct Body: Codable {
            let target_language: String
            let web_search_provider: String
            let web_search_enabled: Bool
            let tavily_api_key: String?
            let ocr_cloud_base_url: String?
            let ocr_cloud_model: String?
            let ocr_cloud_api_key: String?
            let ocr_cloud_timeout_seconds: Double?
            let debug_mode: Bool?
            let auto_start_summary: Bool?
            let models: ModelsSettings?
            let prompts: PromptsSettings?
        }
        let body = try JSONEncoder().encode(
            Body(
                target_language: targetLanguage,
                web_search_provider: webSearchProvider,
                web_search_enabled: webSearchEnabled,
                tavily_api_key: tavilyAPIKey,
                ocr_cloud_base_url: ocrCloudBaseURL,
                ocr_cloud_model: ocrCloudModel,
                ocr_cloud_api_key: ocrCloudAPIKey,
                ocr_cloud_timeout_seconds: ocrCloudTimeoutSeconds,
                debug_mode: debugMode,
                auto_start_summary: autoStartSummary,
                models: models,
                prompts: prompts
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

    func fetchOcrStatus() async throws -> OcrStatus {
        let data = try await get(path: "/settings/ocr/status")
        return try await Self.decode(OcrStatus.self, from: data)
    }

    func fetchResourceStatus(resourceId: String) async throws -> ResourceStatus {
        let data = try await get(path: "/settings/resources/\(resourceId)/status")
        return try await Self.decode(ResourceStatus.self, from: data)
    }

    func startContextProbe(
        resourceId: String,
        model: String? = nil,
        baseURL: String? = nil,
        apiKey: String? = nil
    ) async throws -> ContextProbeStatus {
        struct Body: Codable {
            let model: String?
            let base_url: String?
            let api_key: String?
        }
        let body = try JSONEncoder().encode(
            Body(model: model, base_url: baseURL, api_key: apiKey)
        )
        let data = try await post(
            path: "/settings/resources/\(resourceId)/context-probe",
            body: body
        )
        return try await Self.decode(ContextProbeStatus.self, from: data)
    }

    func fetchContextProbe(resourceId: String) async throws -> ContextProbeStatus {
        let data = try await get(path: "/settings/resources/\(resourceId)/context-probe")
        return try await Self.decode(ContextProbeStatus.self, from: data)
    }

    func cancelContextProbe(resourceId: String) async throws {
        _ = try await post(
            path: "/settings/resources/\(resourceId)/context-probe/cancel",
            body: Data("{}".utf8)
        )
    }

    func fetchOpsOverview() async throws -> OpsOverview {
        let data = try await get(path: "/ops/overview")
        return try await Self.decode(OpsOverview.self, from: data)
    }

    func fetchOpsTasks(status: String? = nil) async throws -> OpsTasksResponse {
        var path = "/ops/tasks"
        if let status, !status.isEmpty {
            path += "?status=\(status.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? status)"
        }
        let data = try await get(path: path)
        return try await Self.decode(OpsTasksResponse.self, from: data)
    }

    func cancelOpsTask(id: String) async throws {
        _ = try await post(path: "/ops/tasks/\(id)/cancel", body: Data("{}".utf8))
    }

    func fetchResourceRuntime() async throws -> ResourceRuntimeResponse {
        let data = try await get(path: "/ops/resources/runtime")
        return try await Self.decode(ResourceRuntimeResponse.self, from: data)
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
        onStatus: ((String) -> Void)? = nil,
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
            if obj["type"] as? String == "status", let status = obj["message"] as? String {
                onStatus?(status)
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
                final = ChatResponse.fromSSEDone(obj, citations: [])
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

    /// Long-running GET (segment list for large books): extended timeout, no retry storm.
    private func getLongRunning(path: String, queryItems: [URLQueryItem]? = nil) async throws -> Data {
        let (data, resp) = try await Self.longSession.data(from: url(path: path, queryItems: queryItems))
        try validate(resp: resp, data: data)
        return data
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
        if Self.urlRequestCancelled(self) { return true }
        let ns = self as NSError
        if ns.domain == "CoreClient", ns.code == 499 { return true }
        if let underlying = ns.userInfo[NSUnderlyingErrorKey] as? Error {
            if underlying is CancellationError { return true }
            if Self.urlRequestCancelled(underlying) { return true }
        }
        return false
    }

    /// Nil when the failure is just a cancelled in-flight request (not for alerts).
    var userFacingMessage: String? {
        isCancellation ? nil : localizedDescription
    }

    private static func urlRequestCancelled(_ error: Error) -> Bool {
        if let urlError = error as? URLError { return urlError.code == .cancelled }
        let ns = error as NSError
        return ns.domain == NSURLErrorDomain && ns.code == NSURLErrorCancelled
    }
}
