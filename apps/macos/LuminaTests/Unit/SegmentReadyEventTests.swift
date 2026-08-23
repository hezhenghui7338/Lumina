import XCTest
@testable import Lumina

final class SegmentReadyEventTests: XCTestCase {
    private let sampleSummaryJSON = """
    {"sentences":["本段交代主角出身寒门。"],"bullets":[{"label":"寒门出身","body":"主角生于贫苦农家，父亲早逝，母亲靠纺织维生；邻里虽敬其向学，却无力资助书卷。"},{"label":"赴考之志","body":"段末以誓要金榜题名收束，将个人命运与科举制度绑定，暗示后文赶考与权谋冲突。"},{"label":"邻里期望","body":"乡邻将其视为家族与村庄的希望，无形压力与有限资源之间的张力在本段已初现端倪。"}],"notes":[],"follow_ups":["主角与邻里期望之间有何张力？"],"label":"引子：寒门赴考","anchor":"§第一章 · 段 1"}
    """

    func testExtractSummaryJSON_fromStringField() {
        let event: [String: Any] = [
            "type": "segment_ready",
            "idx": 0,
            "summary_json": sampleSummaryJSON,
        ]
        let json = SegmentReadyEventParser.extractSummaryJSON(from: event)
        XCTAssertEqual(json, sampleSummaryJSON)
        XCTAssertNotNil(ParsedSummary(json: json ?? ""))
    }

    func testExtractSummaryJSON_fromDictionaryField() {
        guard let data = sampleSummaryJSON.data(using: .utf8),
              let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else {
            XCTFail("fixture parse failed")
            return
        }
        let event: [String: Any] = [
            "type": "segment_ready",
            "idx": NSNumber(value: 2),
            "summary_json": dict,
        ]
        let json = SegmentReadyEventParser.extractSummaryJSON(from: event)
        XCTAssertNotNil(json)
        XCTAssertNotNil(ParsedSummary(json: json ?? ""))
    }

    func testExtractSummaryJSON_fromFlatFields() {
        let event: [String: Any] = [
            "type": "segment_ready",
            "idx": 1,
            "label": "引子：寒门赴考",
            "anchor": "§第一章 · 段 1",
            "sentences": ["本段交代主角出身寒门。"],
            "bullets": [
                ["label": "寒门出身", "body": "主角生于贫苦农家，父亲早逝，母亲靠纺织维生；邻里虽敬其向学，却无力资助书卷。"],
                ["label": "赴考之志", "body": "段末以誓要金榜题名收束，将个人命运与科举制度绑定，暗示后文赶考与权谋冲突。"],
                ["label": "邻里期望", "body": "乡邻将其视为家族与村庄的希望，无形压力与有限资源之间的张力在本段已初现端倪。"],
            ],
            "notes": [],
            "follow_ups": ["主角与邻里期望之间有何张力？"],
        ]
        let json = SegmentReadyEventParser.extractSummaryJSON(from: event)
        XCTAssertNotNil(json)
        let parsed = ParsedSummary(json: json ?? "")
        XCTAssertNotNil(parsed)
        XCTAssertFalse(parsed?.sentences.isEmpty ?? true)
        XCTAssertEqual(parsed?.bullets.count, 3)
    }

    func testEventIndex_acceptsNSNumber() {
        let event: [String: Any] = ["idx": NSNumber(value: 4)]
        XCTAssertEqual(SegmentReadyEventParser.eventIndex(from: event), 4)
    }

    func testParseBatch_offMainThread() {
        let json = sampleSummaryJSON
        let parsed = ParsedSummary.parseBatch([(0, json), (1, json)])
        XCTAssertEqual(parsed.count, 2)
        XCTAssertNotNil(parsed[0])
        XCTAssertEqual(parsed[0]?.bullets.count, 3)
    }

    func testBulletPreviewLine() {
        let parsed = ParsedSummary(json: sampleSummaryJSON)
        XCTAssertEqual(parsed?.bulletPreviewLine, "寒门出身：主角生于贫苦农家，父亲早逝，母亲靠纺织维生；邻里虽敬其向学，却无力资助书卷。")
    }

    func testFormatBulletsPreview_matchesParseBullets() {
        let preview = SegmentReadyEventParser.formatBulletsPreview(sampleSummaryJSON)
        XCTAssertNotNil(preview)
        XCTAssertTrue(preview?.contains("寒门出身") ?? false)
        let bullets = SegmentReadyEventParser.parseBullets(sampleSummaryJSON)
        XCTAssertEqual(preview, bullets.joined(separator: " · "))
    }

    func testParsedSummary_legacyStringBullets() {
        let json = """
        {"sentences":["一句概述。"],"bullets":["寒门出身：主角生于贫苦农家。","赴考之志：段末誓要金榜题名。","邻里期望：乡邻将其视为希望。"],"anchor":"段 1"}
        """
        let parsed = ParsedSummary(json: json)
        XCTAssertNotNil(parsed)
        XCTAssertTrue(parsed?.hasContent ?? false)
        XCTAssertEqual(parsed?.bullets.count, 3)
        XCTAssertEqual(parsed?.bullets.first?.label, "寒门出身")
    }

    func testParsedSummary_markdownFence() {
        let json = """
        ```json
        {"sentences":["一句概述。"],"bullets":[{"label":"要点一","body":"第一条要点的充实说明，包含足够细节内容。"},{"label":"要点二","body":"第二条要点的充实说明，包含足够细节内容。"},{"label":"要点三","body":"第三条要点的充实说明，包含足够细节内容。"}],"anchor":"§测试 · 段 1"}
        ```
        """
        let parsed = ParsedSummary(json: json)
        XCTAssertNotNil(parsed)
        XCTAssertTrue(parsed?.hasContent ?? false)
        XCTAssertEqual(parsed?.bullets.count, 3)
    }

    func testParsedSummary_proseWrappedJSON() {
        let json = """
        说明文字在前。
        {"sentences":["一句概述。"],"bullets":[{"label":"要点一","body":"第一条要点的充实说明，包含足够细节内容。"},{"label":"要点二","body":"第二条要点的充实说明，包含足够细节内容。"},{"label":"要点三","body":"第三条要点的充实说明，包含足够细节内容。"}],"anchor":"§段 1"}
        后面还有说明。
        """
        let parsed = ParsedSummary(json: json)
        XCTAssertNotNil(parsed)
        XCTAssertTrue(parsed?.hasContent ?? false)
        XCTAssertEqual(parsed?.sentences.count, 1)
    }

    func testParsedSummary_invalidJSON_returnsNil() {
        XCTAssertNil(ParsedSummary(json: "not json"))
    }
}

@MainActor
final class ReaderSummaryRefreshTests: XCTestCase {
    func testSegmentReady_replacesCachedSummaryAfterResummarize() async {
        let viewModel = ReaderViewModel()
        viewModel.segments = [
            SegmentRow(
                id: "s0",
                idx: 0,
                label: "旧标题",
                chapter: nil,
                summary_status: "ready",
                summary_json: Self.summaryJSON("旧摘要。"),
                raw_text: nil,
                translation: nil,
                anchor_label: nil,
                summary_provider: nil,
                summary_model: nil,
                summary_tier: nil,
                char_count: nil,
                retry_count: nil,
                summary_duration_s: nil,
                summary_llm_attempts: nil
            ),
        ]
        let core = CoreClient(baseURL: URL(string: "http://127.0.0.1:8765")!)

        viewModel.handleEvent(Self.readyEvent(sentence: "旧摘要。"), core: core)
        let firstReady = await Self.waitUntil {
            viewModel.parsedSummary(for: 0)?.sentences.first == "旧摘要。"
        }
        XCTAssertTrue(firstReady, "first summary should parse into the reader cache")

        viewModel.handleEvent(Self.readyEvent(sentence: "新摘要。"), core: core)
        let replaced = await Self.waitUntil {
            viewModel.parsedSummary(for: 0)?.sentences.first == "新摘要。"
        }
        XCTAssertTrue(replaced, "re-summarize must replace the cached parsed summary without leaving the reader")
        XCTAssertEqual(viewModel.segments[0].summary_json, Self.summaryJSON("新摘要。"))
    }

    func testSegmentReady_sameJSON_keepsExistingParse() async {
        let viewModel = ReaderViewModel()
        viewModel.segments = [
            SegmentRow(
                id: "s0",
                idx: 0,
                label: nil,
                chapter: nil,
                summary_status: "ready",
                summary_json: Self.summaryJSON("同一句。"),
                raw_text: nil,
                translation: nil,
                anchor_label: nil,
                summary_provider: nil,
                summary_model: nil,
                summary_tier: nil,
                char_count: nil,
                retry_count: nil,
                summary_duration_s: nil,
                summary_llm_attempts: nil
            ),
        ]
        let core = CoreClient(baseURL: URL(string: "http://127.0.0.1:8765")!)
        viewModel.handleEvent(Self.readyEvent(sentence: "同一句。"), core: core)
        let parsed = await Self.waitUntil { viewModel.parsedSummary(for: 0) != nil }
        XCTAssertTrue(parsed)
        let first = viewModel.parsedSummary(for: 0)

        viewModel.handleEvent(Self.readyEvent(sentence: "同一句。"), core: core)
        try? await Task.sleep(nanoseconds: 80_000_000)
        XCTAssertEqual(viewModel.parsedSummary(for: 0), first)
    }

    private static func summaryJSON(_ sentence: String) -> String {
        """
        {"sentences":["\(sentence)"],"bullets":[{"label":"要点","body":"说明文字。"}],"notes":[],"follow_ups":[],"label":"段","anchor":"段 1"}
        """
    }

    private static func readyEvent(sentence: String) -> [String: Any] {
        [
            "type": "segment_ready",
            "idx": 0,
            "summary_status": "ready",
            "label": "段",
            "summary_json": summaryJSON(sentence),
        ]
    }

    private static func waitUntil(
        timeout: TimeInterval = 1.0,
        _ condition: () -> Bool
    ) async -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if condition() { return true }
            try? await Task.sleep(nanoseconds: 20_000_000)
        }
        return condition()
    }
}
