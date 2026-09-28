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
        XCTAssertEqual(rows.compactMap { $0.segment?.idx }, [0, 1])
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

    func testDisplayPath_capsAtTwoTitleLevelsWithoutMerging() {
        XCTAssertEqual(
            SegmentOutlinePolicy.displayPath(["合集", "咸丰元年", "致诸弟"]),
            ["合集", "咸丰元年"]
        )
        XCTAssertEqual(
            SegmentOutlinePolicy.displayPath(["曾国藩全集1", "咸丰十年"]),
            ["曾国藩全集1", "咸丰十年"]
        )
        XCTAssertEqual(
            SegmentOutlinePolicy.displayPath([
                "曾国藩全集1", "道光三十年", "003. 应诏陈言疏三月初二日",
            ]),
            ["曾国藩全集1", "道光三十年"]
        )
        XCTAssertEqual(
            SegmentOutlinePolicy.displayPath(["曾国藩全集11", "同治八年", "七月"]),
            ["曾国藩全集11", "同治八年"]
        )
        XCTAssertEqual(
            SegmentOutlinePolicy.displayPath(["曾国藩全集13", "目录", "篇目"]),
            ["曾国藩全集13", "目录"]
        )
        XCTAssertEqual(
            SegmentOutlinePolicy.displayPath(["2.6 Lambda表达式", "2.6 Lambda表达式"]),
            ["2.6 Lambda表达式"]
        )
        XCTAssertEqual(
            SegmentOutlinePolicy.displayPath([
                "第一部分 创建爬虫", "第 2 章 复杂 HTML 解析", "2.4 正则",
            ]),
            ["第一部分 创建爬虫", "第 2 章 复杂 HTML 解析"]
        )
        XCTAssertEqual(
            SegmentOutlinePolicy.displayPath([
                "第 2 章 复杂 HTML 解析", "2.4 正则", "2.4.1 细节",
            ]),
            ["第 2 章 复杂 HTML 解析", "2.4 正则"]
        )
        XCTAssertEqual(SegmentOutlinePolicy.displayPath(["序言"]), ["序言"])
        XCTAssertEqual(SegmentOutlinePolicy.displayPath([]), [])
    }

    func testBuild_zengGuofanKeepsVolumeYearSegmentOnly() {
        let segments = [
            row(idx: 0, headingPath: ["曾国藩全集1", "道光三十年", "002．疏正月"], label: "疏"),
            row(idx: 1, headingPath: ["曾国藩全集1", "道光三十年", "003．疏三月"], label: "疏二"),
            row(idx: 2, headingPath: ["曾国藩全集1", "咸丰元年", "七月"], label: "折"),
        ]
        let rows = SegmentOutlinePolicy.build(segments: segments, collapsed: [])
        XCTAssertEqual(rows.filter(\.isHeader).map(\.title), [
            "曾国藩全集1", "道光三十年", "咸丰元年",
        ])
        XCTAssertFalse(rows.contains { $0.title.contains("疏") || $0.title == "七月" })
        XCTAssertEqual(rows.compactMap { $0.segment?.idx }, [0, 1, 2])
    }

    func testBuild_revisitedYearHeadersHaveUniqueIds() {
        // Diary volumes can briefly interleave an earlier year; header pathKeys
        // collide unless ids include the emission segment idx.
        let segments = [
            row(idx: 0, headingPath: ["曾国藩全集16", "道光二十一年"], label: "甲"),
            row(idx: 1, headingPath: ["曾国藩全集16", "道光十九年"], label: "错挂"),
            row(idx: 2, headingPath: ["曾国藩全集16", "道光二十一年"], label: "乙"),
        ]
        let rows = SegmentOutlinePolicy.build(segments: segments, collapsed: [])
        let headerIds = rows.filter(\.isHeader).map(\.id)
        XCTAssertEqual(headerIds.count, Set(headerIds).count)
        let year21 = rows.filter { $0.isHeader && $0.title == "道光二十一年" }
        XCTAssertEqual(year21.count, 2)
        XCTAssertEqual(year21.map(\.pathKey), [
            "曾国藩全集16/道光二十一年",
            "曾国藩全集16/道光二十一年",
        ])
        XCTAssertNotEqual(year21[0].id, year21[1].id)
    }

    func testBuild_compressesDeepTocToTwoTitleLevelsPlusSegment() {
        let segments = [
            row(idx: 0, headingPath: ["合集", "咸丰元年", "致诸弟"], label: "家事"),
            row(idx: 1, headingPath: ["合集", "咸丰元年", "致诸弟"], label: "续"),
            row(idx: 2, headingPath: ["合集", "咸丰二年", "复胡林翼"], label: "军务"),
        ]
        let rows = SegmentOutlinePolicy.build(segments: segments, collapsed: [])
        XCTAssertEqual(rows.map(\.title), [
            "合集", "咸丰元年", "", "",
            "咸丰二年", "",
        ])
        XCTAssertEqual(rows.map(\.isHeader), [
            true, true, false, false,
            true, false,
        ])
        XCTAssertEqual(rows.map(\.depth), [
            0, 1, 2, 2,
            1, 2,
        ])
        XCTAssertEqual(
            rows.first { $0.pathKey == "合集" }?.headerCount,
            3
        )
        XCTAssertEqual(
            SegmentOutlinePolicy.keysToReveal(for: 2, in: segments),
            ["合集", "合集/咸丰二年"]
        )
        // resolvePath still returns stored path; displayPath caps depth.
        XCTAssertEqual(
            SegmentOutlinePolicy.resolvePath(
                row(idx: 9, chapter: "§合集 · 年份 · 文章")
            ),
            ["合集", "年份", "文章"]
        )
        XCTAssertEqual(
            SegmentOutlinePolicy.displayPath(
                SegmentOutlinePolicy.resolvePath(
                    row(idx: 9, chapter: "§合集 · 年份 · 文章")
                )
            ),
            ["合集", "年份"]
        )
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
        XCTAssertEqual(rows.compactMap { $0.segment?.idx }, [2])
        XCTAssertTrue(rows.first { $0.pathKey == "第一部分/第一章" }?.isCollapsed == true)
    }

    func testBuild_collapsesPartHidesNestedHeaders() {
        let segments = [
            row(idx: 0, headingPath: ["第一部分", "第一章"]),
            row(idx: 1, headingPath: ["第二部分"]),
        ]
        let rows = SegmentOutlinePolicy.build(segments: segments, collapsed: ["第一部分"])
        XCTAssertEqual(rows.map(\.title), ["第一部分", "第二部分", ""])
        XCTAssertEqual(rows.compactMap { $0.segment?.idx }, [1])
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

    func testAllFoldableKeys_collectsEveryHeader() {
        let segments = [
            row(idx: 0, headingPath: ["合集", "咸丰元年"]),
            row(idx: 1, headingPath: ["合集", "咸丰二年"]),
            row(idx: 2, headingPath: ["附录"]),
        ]
        XCTAssertEqual(
            SegmentOutlinePolicy.allFoldableKeys(in: segments),
            ["合集", "合集/咸丰元年", "合集/咸丰二年", "附录"]
        )
        XCTAssertEqual(
            SegmentOutlinePolicy.allFoldableKeys(in: [row(idx: 0, label: "平铺")]),
            []
        )
    }

    func testBulkToggle_collapsesAllHeadersThenExpands() {
        let segments = [
            row(idx: 0, headingPath: ["合集", "咸丰元年"]),
            row(idx: 1, headingPath: ["合集", "咸丰二年"]),
        ]
        let keys = SegmentOutlinePolicy.allFoldableKeys(in: segments)
        XCTAssertEqual(
            SegmentOutlinePolicy.bulkToggleAction(collapsed: [], foldableKeys: keys),
            .collapseAll
        )
        let collapsed = SegmentOutlinePolicy.applyingBulkToggle(
            collapsed: [],
            foldableKeys: keys
        )
        XCTAssertEqual(collapsed, keys)
        XCTAssertTrue(
            SegmentOutlinePolicy.isFullyCollapsed(collapsed: collapsed, foldableKeys: keys)
        )
        let afterCollapse = SegmentOutlinePolicy.build(segments: segments, collapsed: collapsed)
        XCTAssertEqual(afterCollapse.map(\.title), ["合集"])
        XCTAssertTrue(afterCollapse.allSatisfy(\.isHeader))
        XCTAssertEqual(
            SegmentOutlinePolicy.bulkToggleAction(collapsed: collapsed, foldableKeys: keys),
            .expandAll
        )
        XCTAssertEqual(
            SegmentOutlinePolicy.applyingBulkToggle(collapsed: collapsed, foldableKeys: keys),
            []
        )
        // Partial collapse still offers collapse-all (not expand).
        XCTAssertEqual(
            SegmentOutlinePolicy.bulkToggleAction(
                collapsed: ["合集/咸丰元年"],
                foldableKeys: keys
            ),
            .collapseAll
        )
        XCTAssertNil(
            SegmentOutlinePolicy.bulkToggleAction(collapsed: [], foldableKeys: [])
        )
    }

    func testReplaceSegment_patchesLeafWithoutChangingTreeShape() {
        let segments = [
            row(idx: 0, headingPath: ["卷一"], label: "旧"),
            row(idx: 1, headingPath: ["卷一"], label: "乙"),
        ]
        var rows = SegmentOutlinePolicy.build(segments: segments, collapsed: [])
        var updated = segments[0]
        updated.summary_status = "ready"
        updated.label = "新"
        XCTAssertTrue(SegmentOutlinePolicy.replaceSegment(updated, in: &rows))
        XCTAssertEqual(rows.compactMap { $0.segment?.idx }, [0, 1])
        XCTAssertEqual(rows.first { $0.segment?.idx == 0 }?.segment?.label, "新")
        XCTAssertFalse(
            SegmentOutlinePolicy.structureChanged(from: segments[0], to: updated)
        )
        var rechaptered = updated
        rechaptered.chapter = "卷二"
        rechaptered.heading_path = ["卷二"]
        XCTAssertTrue(SegmentOutlinePolicy.structureChanged(from: updated, to: rechaptered))
    }
}
