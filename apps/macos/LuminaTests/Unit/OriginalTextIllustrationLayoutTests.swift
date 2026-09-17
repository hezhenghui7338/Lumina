import XCTest
@testable import Lumina

final class OriginalTextIllustrationLayoutTests: XCTestCase {
    func testNoIllustrationsReturnsSingleTextPart() {
        let parts = OriginalTextIllustrationLayout.parts(
            text: "hello world",
            illustrations: []
        )
        XCTAssertEqual(parts.count, 1)
        guard case .text(let text) = parts[0] else {
            return XCTFail("expected text")
        }
        XCTAssertEqual(text, "hello world")
    }

    func testSplitsAroundOffsets() {
        let illustrations = [
            SegmentIllustration(
                asset_id: "a1",
                char_offset: 5,
                alt: "图",
                url: nil,
                width: 100,
                height: 80,
                mime: "image/png"
            )
        ]
        let parts = OriginalTextIllustrationLayout.parts(
            text: "hello world",
            illustrations: illustrations
        )
        XCTAssertEqual(parts.count, 3)
        guard case .text(let left) = parts[0] else { return XCTFail("left") }
        guard case .image(let img) = parts[1] else { return XCTFail("image") }
        guard case .text(let right) = parts[2] else { return XCTFail("right") }
        XCTAssertEqual(left, "hello")
        XCTAssertEqual(img.asset_id, "a1")
        XCTAssertEqual(right, " world")
    }
}
