import XCTest
@testable import Lumina

final class SegmentBoundaryOffsetTests: XCTestCase {
    func testUnicodeOffset_countsBmpAndSurrogatePair() {
        let text = "学而😊时习"
        XCTAssertEqual(SegmentBoundaryOffset.unicodeOffset(utf16Index: 0, in: text), 0)
        XCTAssertEqual(SegmentBoundaryOffset.unicodeOffset(utf16Index: 2, in: text), 2)
        XCTAssertEqual(SegmentBoundaryOffset.unicodeOffset(utf16Index: 4, in: text), 3)
        XCTAssertEqual(
            SegmentBoundaryOffset.unicodeOffset(utf16Index: 3, in: text),
            2,
            "a trail surrogate must snap back to the scalar start"
        )
        XCTAssertEqual(
            SegmentBoundaryOffset.unicodeOffset(utf16Index: (text as NSString).length, in: text),
            text.unicodeScalars.count
        )
    }

    func testUtf16Index_roundTripsUnicodeOffset() {
        let text = "左侧。😊右侧。"
        for offset in 0...text.unicodeScalars.count {
            let utf16 = SegmentBoundaryOffset.utf16Index(forUnicodeOffset: offset, in: text)
            XCTAssertEqual(SegmentBoundaryOffset.unicodeOffset(utf16Index: utf16, in: text), offset)
        }
    }

    func testSplit_preservesCoverageAndEmoji() {
        let text = "左侧。😊右侧。"
        let (left, right) = SegmentBoundaryOffset.split(text, unicodeOffset: 4)
        XCTAssertEqual(left, "左侧。😊")
        XCTAssertEqual(right, "右侧。")
        XCTAssertEqual(left + right, text)
    }

    func testSplit_clampsEnds() {
        let text = "abc"
        XCTAssertEqual(SegmentBoundaryOffset.split(text, unicodeOffset: 0).0, "")
        XCTAssertEqual(SegmentBoundaryOffset.split(text, unicodeOffset: 0).1, "abc")
        XCTAssertEqual(SegmentBoundaryOffset.split(text, unicodeOffset: 99).0, "abc")
        XCTAssertEqual(SegmentBoundaryOffset.split(text, unicodeOffset: 99).1, "")
    }

    func testEditorDropsDragAndStepControls() throws {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let source = try String(
            contentsOf: macosRoot.appendingPathComponent(
                "Lumina/Features/Reader/SegmentBoundaryEditor.swift"
            ),
            encoding: .utf8
        )
        XCTAssertFalse(source.contains("上一处"))
        XCTAssertFalse(source.contains("下一处"))
        XCTAssertFalse(source.contains("拖动调整"))
        XCTAssertFalse(source.contains("DragGesture"))
        XCTAssertTrue(source.contains("点击正文中要作为新分界的位置"))
        XCTAssertTrue(source.contains("点击后立即保存并重新摘要这两段"))
        XCTAssertTrue(source.contains("characterIndexForInsertion"))
    }
}
