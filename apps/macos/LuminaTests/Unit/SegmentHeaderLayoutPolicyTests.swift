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

    func testContentMeta_formatsCharCountWithOriginalPrefix() {
        XCTAssertEqual(
            SegmentContentMetaPolicy.label(charCount: 2494),
            "原文 · 约 \(SegmentContentMetaPolicy.formatCount(2494)) 字"
        )
    }

    func testContentMeta_omitsWhenCharCountMissingOrZero() {
        XCTAssertNil(SegmentContentMetaPolicy.label(charCount: nil))
        XCTAssertNil(SegmentContentMetaPolicy.label(charCount: 0))
        XCTAssertEqual(SegmentContentMetaPolicy.label(charCount: 100), "原文 · 约 100 字")
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
