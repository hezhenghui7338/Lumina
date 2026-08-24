import XCTest
@testable import Lumina

final class SegmentHeaderLayoutPolicyTests: XCTestCase {
    func testTrailingItems_turnButtonsStayLastAcrossMetadataVariants() {
        let variants: [(progress: Bool, regenerate: Bool, charCount: Bool, index: Bool)] = [
            (false, false, true, true),
            (false, true, true, true),
            (true, false, false, true),
            (true, false, true, true),
            (false, true, false, true),
            (false, false, false, true),
            (false, true, true, false),
        ]
        for variant in variants {
            let items = SegmentHeaderLayoutPolicy.trailingItems(
                isSummaryInProgress: variant.progress,
                showsRegenerate: variant.regenerate,
                showsCharCount: variant.charCount,
                showsSegmentIndex: variant.index,
                showsTurnButtons: true
            )
            XCTAssertEqual(
                items.last,
                .turnButtons,
                "progress=\(variant.progress) regenerate=\(variant.regenerate) charCount=\(variant.charCount) index=\(variant.index)"
            )
        }
    }

    func testTrailingItems_readySegmentOrderPinsTurnButtonsAfterVariableText() {
        XCTAssertEqual(
            SegmentHeaderLayoutPolicy.trailingItems(
                isSummaryInProgress: false,
                showsRegenerate: true,
                showsCharCount: true,
                showsSegmentIndex: true,
                showsTurnButtons: true
            ),
            [.regenerateSummary, .charCount, .segmentIndex, .turnButtons]
        )
    }

    func testTrailingItems_omitsTurnButtonsWhenHidden() {
        let items = SegmentHeaderLayoutPolicy.trailingItems(
            isSummaryInProgress: false,
            showsRegenerate: true,
            showsCharCount: true,
            showsSegmentIndex: true,
            showsTurnButtons: false
        )
        XCTAssertFalse(items.contains(.turnButtons))
        XCTAssertEqual(items.last, .segmentIndex)
    }
}
