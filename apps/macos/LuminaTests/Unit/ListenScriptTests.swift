import XCTest
@testable import Lumina

final class ListenScriptTests: XCTestCase {
    private let sampleJSON = """
    {"sentences":["本段交代主角出身寒门。","邻里敬其向学却无力资助。"],"bullets":[{"label":"寒门出身","body":"主角生于贫苦农家，父亲早逝。"},{"label":"赴考之志","body":"段末以金榜题名收束。"},{"label":"邻里期望","body":"乡邻视为村庄的希望。"}],"notes":["后文将出现权谋冲突。"],"follow_ups":["主角与邻里期望之间有何张力？"],"label":"引子","anchor":"§第一章 · 段 1"}
    """

    func testSummaryLayerLabels() {
        XCTAssertEqual(ListenMode.summary.label, "听简要摘要")
        XCTAssertEqual(ListenMode.detailed.label, "听完整摘要")
        XCTAssertEqual(ListenMode.summary.shortLabel, "简要摘要")
        XCTAssertEqual(ListenMode.detailed.shortLabel, "完整摘要")
    }

    func testSummaryModeIsSentencesOnly() {
        let parsed = ParsedSummary(json: sampleJSON)
        XCTAssertNotNil(parsed)
        let script = ListenScript.build(mode: .summary, summary: parsed, rawText: nil)
        XCTAssertTrue(script.ready)
        XCTAssertEqual(script.texts, [
            "本段交代主角出身寒门。",
            "邻里敬其向学却无力资助。",
        ])
        let joined = script.texts.joined(separator: "\n")
        XCTAssertFalse(joined.contains("你可以接着问"))
        XCTAssertFalse(joined.contains("主角与邻里期望之间有何张力？"))
        XCTAssertFalse(joined.contains(ListenScript.sectionBullets))
    }

    func testDetailedModeIncludesBulletsNotNotesOrFollowUps() {
        let parsed = ParsedSummary(json: sampleJSON)!
        let script = ListenScript.build(mode: .detailed, summary: parsed, rawText: nil)
        XCTAssertTrue(script.ready)
        XCTAssertEqual(script.texts.first, "本段交代主角出身寒门。")
        XCTAssertTrue(script.texts.contains(ListenScript.sectionBullets))
        XCTAssertTrue(script.texts.contains("1. 寒门出身。主角生于贫苦农家，父亲早逝。"))
        XCTAssertTrue(script.texts.contains("2. 赴考之志。段末以金榜题名收束。"))
        XCTAssertFalse(script.texts.contains(ListenScript.sectionNotes))
        XCTAssertFalse(script.texts.contains("后文将出现权谋冲突。"))
        let joined = script.texts.joined(separator: "\n")
        XCTAssertFalse(joined.contains("你可以接着问"))
        XCTAssertFalse(joined.contains("主角与邻里期望之间有何张力？"))
    }

    func testOriginalSplitsSentences() {
        let script = ListenScript.build(
            mode: .original,
            summary: nil,
            rawText: "第一句。第二句！第三句？"
        )
        XCTAssertTrue(script.ready)
        XCTAssertEqual(script.texts.first, "第一句。")
        XCTAssertTrue(script.texts.contains("第二句！"))
        XCTAssertTrue(script.texts.contains("第三句？"))
    }

    func testMissingSummaryIsNotReady() {
        let script = ListenScript.build(mode: .summary, summary: nil, rawText: nil)
        XCTAssertFalse(script.ready)
        XCTAssertEqual(script.skipReason, "summary_not_ready")
        XCTAssertTrue(script.texts.isEmpty)
    }

    func testEmptyOriginalIsNotReady() {
        let script = ListenScript.build(mode: .original, summary: nil, rawText: "   ")
        XCTAssertFalse(script.ready)
        XCTAssertEqual(script.skipReason, "empty_text")
    }

    func testDetectLanguage() {
        XCTAssertEqual(ListenScript.detectLanguage("本段交代主角出身寒门。"), "zh")
        XCTAssertEqual(ListenScript.detectLanguage("The hero leaves home at dawn."), "en")
    }
}

final class ListenSessionTests: XCTestCase {
    func testAdvancePlaysReadySegment() {
        XCTAssertEqual(
            ListenAdvancePolicy.decide(
                idx: 2,
                segmentCount: 10,
                ready: true,
                skipReason: nil,
                consecutiveSkips: 0
            ),
            .play(2)
        )
    }

    func testAdvanceSkipsUnreadyThenContinues() {
        XCTAssertEqual(
            ListenAdvancePolicy.decide(
                idx: 1,
                segmentCount: 10,
                ready: false,
                skipReason: "summary_not_ready",
                consecutiveSkips: 0
            ),
            .skip(idx: 2, reason: "summary_not_ready")
        )
    }

    func testAdvancePausesAfterConsecutiveSkips() {
        XCTAssertEqual(
            ListenAdvancePolicy.decide(
                idx: 4,
                segmentCount: 10,
                ready: false,
                skipReason: "summary_not_ready",
                consecutiveSkips: 2
            ),
            .pauseTooManySkips(idx: 4)
        )
    }

    func testAdvanceFinishesAtEnd() {
        XCTAssertEqual(
            ListenAdvancePolicy.decide(
                idx: 10,
                segmentCount: 10,
                ready: true,
                skipReason: nil,
                consecutiveSkips: 0
            ),
            .finished
        )
    }

    func testAdvanceFinishWhenSkipWouldPassEnd() {
        XCTAssertEqual(
            ListenAdvancePolicy.decide(
                idx: 9,
                segmentCount: 10,
                ready: false,
                skipReason: "summary_not_ready",
                consecutiveSkips: 0
            ),
            .finished
        )
    }
}
