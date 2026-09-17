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
        // summary JSON label is not spoken unless passed as segmentLabel
        XCTAssertFalse(script.texts.contains("引子"))
    }

    func testSummaryModePrependsSegmentLabel() {
        let parsed = ParsedSummary(json: sampleJSON)!
        let script = ListenScript.build(
            mode: .summary, summary: parsed, rawText: nil, segmentLabel: "引子"
        )
        XCTAssertEqual(script.texts, [
            "引子",
            "本段交代主角出身寒门。",
            "邻里敬其向学却无力资助。",
        ])
    }

    func testBlankSegmentLabelIsSkipped() {
        let parsed = ParsedSummary(json: sampleJSON)!
        let script = ListenScript.build(
            mode: .summary, summary: parsed, rawText: nil, segmentLabel: "   "
        )
        XCTAssertEqual(script.texts.first, "本段交代主角出身寒门。")
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

    func testDetailedPrependsSegmentLabel() {
        let parsed = ParsedSummary(json: sampleJSON)!
        let script = ListenScript.build(
            mode: .detailed, summary: parsed, rawText: nil, segmentLabel: "引子"
        )
        XCTAssertEqual(script.texts.first, "引子")
        XCTAssertEqual(script.texts[1], "本段交代主角出身寒门。")
        XCTAssertTrue(script.texts.contains(ListenScript.sectionBullets))
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

    func testOriginalPrependsSegmentLabel() {
        let script = ListenScript.build(
            mode: .original,
            summary: nil,
            rawText: "第一句。第二句！",
            segmentLabel: "开篇"
        )
        XCTAssertEqual(script.texts.first, "开篇")
        XCTAssertEqual(script.texts[1], "第一句。")
        XCTAssertTrue(script.texts.contains("第二句！"))
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

    func testSummaryAnchorsMatchUtterances() {
        let parsed = ParsedSummary(json: sampleJSON)!
        let script = ListenScript.build(
            mode: .summary, summary: parsed, rawText: nil, segmentLabel: "引子"
        )
        XCTAssertEqual(script.utterances.map(\.anchor), [
            .segmentTitle,
            .summarySentence(0),
            .summarySentence(1),
        ])
    }

    func testDetailedAnchorsIncludeSectionAndBullets() {
        let parsed = ParsedSummary(json: sampleJSON)!
        let script = ListenScript.build(
            mode: .detailed, summary: parsed, rawText: nil, segmentLabel: "引子"
        )
        XCTAssertEqual(script.utterances.first?.anchor, .segmentTitle)
        XCTAssertTrue(script.utterances.contains { $0.anchor == .sectionBullets })
        XCTAssertTrue(script.utterances.contains { $0.anchor == .bullet(0) })
        XCTAssertTrue(script.utterances.contains { $0.anchor == .bullet(2) })
    }

    func testOriginalAnchorsCarryUTF16Ranges() {
        let raw = "第一句。第二句！"
        let script = ListenScript.build(mode: .original, summary: nil, rawText: raw)
        XCTAssertEqual(script.utterances.count, 2)
        guard case let .originalUTF16(loc0, len0) = script.utterances[0].anchor else {
            return XCTFail("expected originalUTF16")
        }
        let first = (raw as NSString).substring(with: NSRange(location: loc0, length: len0))
        XCTAssertEqual(first, "第一句。")
        guard case let .originalUTF16(loc1, len1) = script.utterances[1].anchor else {
            return XCTFail("expected originalUTF16")
        }
        let second = (raw as NSString).substring(with: NSRange(location: loc1, length: len1))
        XCTAssertEqual(second, "第二句！")
    }

    func testFollowHighlightDoesNotAutoScroll() {
        // Auto-scrolling spoken lines fights continuous play advance (bc-listen-follow-no-autoscroll).
        XCTAssertFalse(ListenFollowHighlightPolicy.scrollsUtteranceIntoView)
    }

    func testAnnounceChapterOnSessionStartAndChange() {
        XCTAssertTrue(
            ListenChapterAnnouncePolicy.shouldAnnounce(
                chapter: "§第十三章 1942年南俄冬季战役",
                context: .sessionStart
            )
        )
        XCTAssertFalse(
            ListenChapterAnnouncePolicy.shouldAnnounce(
                chapter: "第十三章 1942年南俄冬季战役",
                context: .continuing(previousSpokenChapter: "第十三章 1942年南俄冬季战役")
            )
        )
        XCTAssertTrue(
            ListenChapterAnnouncePolicy.shouldAnnounce(
                chapter: "第十三章 1942年南俄冬季战役",
                context: .continuing(previousSpokenChapter: "第十二章 斯大林格勒的悲剧")
            )
        )
    }

    func testChapterThenLabelPrefixOnSessionStart() {
        let parsed = ParsedSummary(json: sampleJSON)!
        let script = ListenScript.build(
            mode: .summary,
            summary: parsed,
            rawText: nil,
            segmentLabel: "南翼战役新动向",
            chapter: "§第十三章 1942年南俄冬季战役",
            chapterContext: .sessionStart
        )
        XCTAssertEqual(Array(script.texts.prefix(2)), [
            "第十三章 1942年南俄冬季战役",
            "南翼战役新动向",
        ])
        XCTAssertEqual(script.utterances[0].anchor, .segmentTitle)
    }

    func testSameChapterSkipsChapterAnnouncement() {
        let parsed = ParsedSummary(json: sampleJSON)!
        let script = ListenScript.build(
            mode: .summary,
            summary: parsed,
            rawText: nil,
            segmentLabel: "南翼战役新动向",
            chapter: "第十三章 1942年南俄冬季战役",
            chapterContext: .continuing(previousSpokenChapter: "第十三章 1942年南俄冬季战役")
        )
        XCTAssertEqual(script.texts.first, "南翼战役新动向")
        XCTAssertFalse(script.texts[0].contains("第十三章"))
    }
}

final class ListenChromePolicyTests: XCTestCase {
    func testSpeakerFollowsVisiblePanelNotOnlyThePicker() {
        XCTAssertFalse(
            ListenChromePolicy.isShowingOriginal(
                contentMode: .summary, sourceExpanded: false, summaryExpanded: false
            ),
            "摘要层默认面板是总结"
        )
        XCTAssertTrue(
            ListenChromePolicy.isShowingOriginal(
                contentMode: .summary, sourceExpanded: true, summaryExpanded: false
            ),
            "摘要层点「切换原文」后喇叭必须听原文"
        )
        XCTAssertTrue(
            ListenChromePolicy.isShowingOriginal(
                contentMode: .original, sourceExpanded: true, summaryExpanded: false
            )
        )
        XCTAssertFalse(
            ListenChromePolicy.isShowingOriginal(
                contentMode: .original, sourceExpanded: true, summaryExpanded: true
            ),
            "原文层点「切换摘要」后喇叭必须听简要摘要"
        )
    }

    func testPrimaryClickAndChevronFollowTheVisiblePanel() {
        XCTAssertEqual(ListenChromePolicy.primaryMode(showingOriginal: false), .summary)
        XCTAssertEqual(ListenChromePolicy.primaryMode(showingOriginal: true), .original)
        XCTAssertTrue(ListenChromePolicy.showsSummaryChevron(showingOriginal: false))
        XCTAssertFalse(ListenChromePolicy.showsSummaryChevron(showingOriginal: true))
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
