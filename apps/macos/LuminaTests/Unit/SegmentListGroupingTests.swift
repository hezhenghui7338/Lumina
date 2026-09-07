import XCTest
@testable import Lumina

final class SegmentListGroupingTests: XCTestCase {
    private func row(
        idx: Int,
        chapter: String? = nil,
        headingPath: [String]? = nil,
        label: String? = nil
    ) -> SegmentRow {
        SegmentRow(
            id: "s\(idx)",
            idx: idx,
            label: label,
            chapter: chapter,
            summary_status: "ready",
            summary_json: nil,
            raw_text: nil,
            translation: nil,
            anchor_label: nil,
            summary_provider: nil,
            summary_model: nil,
            summary_tier: nil,
            char_count: nil,
            retry_count: nil,
            summary_duration_s: nil,
            summary_llm_attempts: nil,
            heading_path: headingPath
        )
    }

    func testResolvePath_prefersHeadingPathAndStripsSectionMark() {
        let segment = row(idx: 0, chapter: "§其它", headingPath: ["§第一部分", "第一章"])
        XCTAssertEqual(
            SegmentOutlinePolicy.resolvePath(segment),
            ["第一部分", "第一章"]
        )
    }

    func testResolvePath_fallsBackToChapterLabel() {
        let segment = row(idx: 0, chapter: "§第一卷 · 第一章")
        XCTAssertEqual(
            SegmentOutlinePolicy.resolvePath(segment),
            ["第一卷", "第一章"]
        )
        XCTAssertEqual(SegmentOutlinePolicy.fromChapter("§序言"), ["序言"])
        XCTAssertEqual(SegmentOutlinePolicy.fromChapter("卷一 §"), ["卷一"])
        XCTAssertEqual(SegmentOutlinePolicy.fromChapter(nil), [])
    }

    func testBuild_flatWhenNoChapters() {
        let segments = [row(idx: 0, label: "a"), row(idx: 1, label: "b")]
        XCTAssertFalse(SegmentOutlinePolicy.shouldGroup(segments))
        let rows = SegmentOutlinePolicy.build(segments: segments, collapsed: [])
        XCTAssertEqual(rows.count, 2)
        XCTAssertTrue(rows.allSatisfy { !$0.isHeader && !$0.grouped })
        XCTAssertEqual(rows.map(\.idx), [0, 1])
    }

    func testBuild_nestsPartChapterAndSegments() {
        let segments = [
            row(idx: 0, headingPath: ["序言"], label: "开场"),
            row(idx: 1, headingPath: ["序言"], label: "缘起"),
            row(idx: 2, headingPath: ["第一部分", "第一章"], label: "入京"),
            row(idx: 3, headingPath: ["第一部分", "第一章"], label: "夜谈"),
            row(idx: 4, headingPath: ["第一部分", "第二章"], label: "离京"),
            row(idx: 5, headingPath: ["第二部分"], label: "尾声"),
        ]
        let rows = SegmentOutlinePolicy.build(segments: segments, collapsed: [])
        XCTAssertEqual(rows.map(\.title), [
            "序言", "", "",
            "第一部分", "第一章", "", "",
            "第二章", "",
            "第二部分", "",
        ])
        XCTAssertEqual(rows.map(\.isHeader), [
            true, false, false,
            true, true, false, false,
            true, false,
            true, false,
        ])
        XCTAssertEqual(rows.map(\.depth), [
            0, 1, 1,
            0, 1, 2, 2,
            1, 2,
            0, 1,
        ])
        XCTAssertEqual(rows.first { $0.pathKey == "序言" }?.headerCount, 2)
        XCTAssertEqual(rows.first { $0.pathKey == "第一部分" }?.headerCount, 3)
        XCTAssertEqual(rows.first { $0.pathKey == "第一部分/第一章" }?.headerCount, 2)
        let grouped = SidebarSegmentItem.make(from: segments[2], grouped: true)
        XCTAssertEqual(grouped.headline, "段 3 · 入京")
        XCTAssertFalse(grouped.headline.contains("第一部分"))
    }

    func testBuild_collapsesNestedChapter() {
        let segments = [
            row(idx: 0, headingPath: ["第一部分", "第一章"]),
            row(idx: 1, headingPath: ["第一部分", "第一章"]),
            row(idx: 2, headingPath: ["第一部分", "第二章"]),
        ]
        let rows = SegmentOutlinePolicy.build(
            segments: segments,
            collapsed: ["第一部分/第一章"]
        )
        XCTAssertEqual(rows.filter(\.isHeader).map(\.title), ["第一部分", "第一章", "第二章"])
        XCTAssertEqual(rows.compactMap(\.idx), [2])
        XCTAssertTrue(rows.first { $0.pathKey == "第一部分/第一章" }?.isCollapsed == true)
    }

    func testBuild_collapsesPartHidesNestedHeaders() {
        let segments = [
            row(idx: 0, headingPath: ["第一部分", "第一章"]),
            row(idx: 1, headingPath: ["第二部分"]),
        ]
        let rows = SegmentOutlinePolicy.build(segments: segments, collapsed: ["第一部分"])
        XCTAssertEqual(rows.map(\.title), ["第一部分", "第二部分", ""])
        XCTAssertEqual(rows.compactMap(\.idx), [1])
    }

    func testKeysToReveal_includesAncestors() {
        let segments = [
            row(idx: 0, headingPath: ["第一部分", "第一章"]),
            row(idx: 1, headingPath: ["第一部分", "第二章"]),
        ]
        XCTAssertEqual(
            SegmentOutlinePolicy.keysToReveal(for: 1, in: segments),
            ["第一部分", "第一部分/第二章"]
        )
    }
}
