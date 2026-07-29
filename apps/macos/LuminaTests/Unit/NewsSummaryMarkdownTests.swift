import XCTest
@testable import Lumina

final class NewsSummaryMarkdownTests: XCTestCase {
    func testParseStructured_extractsSummaryBulletsNotesAndFollowUps() {
        let markdown = """
        ## 总结（最多三句话）
        这是一篇关于 AI 的文章摘要。

        ## 结构化要点
        - **要点一**：说明一 — 依据：原文 〔§Intro〕
        - **要点二**：说明二

        ## 需要注意
        - 样本量较小

        ## 你可以接着问
        1. 这篇文章的核心论点是什么？
        2. 有哪些潜在风险？
        """

        let parsed = NewsSummaryMarkdown.parseStructured(markdown)

        XCTAssertEqual(parsed.sentences, ["这是一篇关于 AI 的文章摘要。"])
        XCTAssertEqual(parsed.bullets.count, 2)
        XCTAssertEqual(parsed.bullets[0].label, "要点一")
        XCTAssertEqual(parsed.bullets[0].body, "说明一")
        XCTAssertEqual(parsed.bullets[1].label, "要点二")
        XCTAssertEqual(parsed.bullets[1].body, "说明二")
        XCTAssertEqual(parsed.notes, ["样本量较小"])
        XCTAssertEqual(parsed.followUps, [
            "这篇文章的核心论点是什么？",
            "有哪些潜在风险？",
        ])
    }

    func testParse_extractsNumberedFollowUps() {
        let markdown = """
        ## 总结（最多三句话）
        这是一篇关于 AI 的文章摘要。

        ## 结构化要点
        - **要点一**：说明一

        ## 你可以接着问
        1. 这篇文章的核心论点是什么？
        2. 有哪些潜在风险？

        """

        let parsed = NewsSummaryMarkdown.parse(markdown)

        XCTAssertTrue(parsed.bodyMarkdown.contains("## 总结"))
        XCTAssertTrue(parsed.bodyMarkdown.contains("## 结构化要点"))
        XCTAssertFalse(parsed.bodyMarkdown.contains("你可以接着问"))
        XCTAssertEqual(parsed.followUps, [
            "这篇文章的核心论点是什么？",
            "有哪些潜在风险？",
        ])
    }

    func testParse_extractsBulletFollowUps() {
        let markdown = """
        ## 总结
        简短总结。

        ## 你可以接着问
        - 第一个问题？
        - 第二个问题？
        """

        let parsed = NewsSummaryMarkdown.parse(markdown)

        XCTAssertEqual(parsed.followUps, ["第一个问题？", "第二个问题？"])
    }

    func testParse_noAskSection_returnsEmptyFollowUps() {
        let markdown = """
        ## 总结
        只有正文，没有引导问题。
        """

        let parsed = NewsSummaryMarkdown.parse(markdown)

        XCTAssertEqual(parsed.followUps, [])
        XCTAssertTrue(parsed.bodyMarkdown.contains("只有正文，没有引导问题。"))
    }

    func testParseStructured_ignoresUnknownSections() {
        let markdown = """
        ## 你可以接着问
        1. 问题 A

        ## 其他
        不应被当作 follow-up
        """

        let parsed = NewsSummaryMarkdown.parseStructured(markdown)

        XCTAssertEqual(parsed.followUps, ["问题 A"])
    }
}

final class NewsArticleCardSkimTests: XCTestCase {
    func testNeedsLLMSkim_sparseArticle() throws {
        let json = """
        {
          "id": "a1",
          "title": "Sparse",
          "excerpt": "Short",
          "one_liner": "Short",
          "detail": null,
          "viewpoints": [],
          "quotes": [],
          "meta": {},
          "reasons": [],
          "url": "https://example.com/a1",
          "skim_rich": false,
          "summary_status": "idle"
        }
        """
        let card = try JSONDecoder().decode(NewsArticleCard.self, from: Data(json.utf8))
        XCTAssertTrue(card.needsLLMSkim)
        XCTAssertFalse(card.hasCachedLLMSummary)
    }

    func testNeedsLLMSkim_richArticle() throws {
        let json = """
        {
          "id": "a2",
          "title": "Rich",
          "excerpt": "One",
          "one_liner": "One",
          "detail": "\(String(repeating: "长", count: 80))",
          "viewpoints": [],
          "quotes": [],
          "meta": {},
          "reasons": [],
          "url": "https://example.com/a2",
          "skim_rich": true,
          "summary_status": "idle"
        }
        """
        let card = try JSONDecoder().decode(NewsArticleCard.self, from: Data(json.utf8))
        XCTAssertFalse(card.needsLLMSkim)
    }
}
