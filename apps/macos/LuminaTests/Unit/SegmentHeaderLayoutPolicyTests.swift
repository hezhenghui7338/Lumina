import XCTest
@testable import Lumina

final class SegmentHeaderLayoutPolicyTests: XCTestCase {
    func testTrailingItems_turnButtonsStayLastAcrossMetadataVariants() {
        let variants: [(meta: Bool, progress: Bool, regenerate: Bool)] = [
            (false, false, false),
            (false, false, true),
            (false, true, false),
            (false, true, true),
            (true, false, false),
            (true, true, true),
        ]
        for variant in variants {
            let items = SegmentHeaderLayoutPolicy.trailingItems(
                showsContentMeta: variant.meta,
                isSummaryInProgress: variant.progress,
                showsRegenerate: variant.regenerate,
                showsTurnButtons: true
            )
            XCTAssertEqual(
                items.last,
                .turnButtons,
                "meta=\(variant.meta) progress=\(variant.progress) regenerate=\(variant.regenerate)"
            )
        }
    }

    func testTrailingItems_readySegmentOrderPinsMetaLeftOfToggle() {
        XCTAssertEqual(
            SegmentHeaderLayoutPolicy.trailingItems(
                showsContentMeta: true,
                isSummaryInProgress: false,
                showsRegenerate: true,
                showsTurnButtons: true
            ),
            [.contentMeta, .panelToggle, .regenerateSummary, .turnButtons]
        )
    }

    func testTrailingItems_panelToggleLeadsWhenMetaHidden() {
        let withoutRegenerate = SegmentHeaderLayoutPolicy.trailingItems(
            showsContentMeta: false,
            isSummaryInProgress: true,
            showsRegenerate: false,
            showsTurnButtons: true
        )
        XCTAssertEqual(withoutRegenerate.first, .panelToggle)
        XCTAssertEqual(withoutRegenerate, [.panelToggle, .progress, .turnButtons])
    }

    func testTrailingItems_omitsTurnButtonsWhenHidden() {
        let items = SegmentHeaderLayoutPolicy.trailingItems(
            showsContentMeta: true,
            isSummaryInProgress: false,
            showsRegenerate: true,
            showsTurnButtons: false
        )
        XCTAssertFalse(items.contains(.turnButtons))
        XCTAssertEqual(items.first, .contentMeta)
        XCTAssertEqual(items.last, .regenerateSummary)
    }

    func testTrailingItems_omitsContentMetaWhenHidden() {
        let items = SegmentHeaderLayoutPolicy.trailingItems(
            showsContentMeta: false,
            isSummaryInProgress: true,
            showsRegenerate: true,
            showsTurnButtons: true
        )
        XCTAssertEqual(items, [.panelToggle, .progress, .regenerateSummary, .turnButtons])
    }

    func testContentMeta_joinsOrdinalAndCharCount() {
        XCTAssertEqual(
            SegmentContentMetaPolicy.label(idx: 149, segmentTotal: 369, charCount: 977),
            "段 150/369 · 约 \(SegmentContentMetaPolicy.formatCount(977)) 字"
        )
        XCTAssertEqual(
            SegmentContentMetaPolicy.label(idx: 0, segmentTotal: 10, charCount: 100),
            "段 1/10 · 约 100 字"
        )
    }

    func testContentMeta_ordinalOnlyWhenCharCountMissingOrZero() {
        XCTAssertEqual(
            SegmentContentMetaPolicy.label(idx: 0, segmentTotal: 10, charCount: nil),
            "段 1/10"
        )
        XCTAssertEqual(
            SegmentContentMetaPolicy.label(idx: 0, segmentTotal: 10, charCount: 0),
            "段 1/10"
        )
        XCTAssertEqual(
            SegmentContentMetaPolicy.label(idx: 0, segmentTotal: 0, charCount: nil),
            "段 1"
        )
    }

    func testSummaryAttribution_formatsProviderModelAndMetrics() {
        XCTAssertEqual(
            SummaryAttributionPolicy.label(
                provider: "aiping",
                model: "gpt-test",
                durationS: 45,
                llmAttempts: 1
            ),
            "摘要 · AiPing · gpt-test · 45s · 1 次尝试"
        )
        XCTAssertNil(
            SummaryAttributionPolicy.label(
                provider: "aiping",
                model: nil,
                durationS: 45,
                llmAttempts: 1
            )
        )
    }
}
