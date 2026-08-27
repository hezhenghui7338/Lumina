import XCTest
@testable import Lumina

final class UsageGuideCopyTests: XCTestCase {
    func testUsageGuide_hasSevenDailySteps() {
        XCTAssertEqual(UsageGuideCopy.title, "使用指南")
        XCTAssertEqual(UsageGuideCopy.items.count, 7)
        XCTAssertEqual(
            UsageGuideCopy.items.map(\.title),
            ["导入", "阅读", "摘要 / 原文", "听", "深聊", "查找", "开始摘要"]
        )
    }

    func testUsageGuide_macChromeMentionsBlankClickAndShortcuts() {
        let bodies = UsageGuideCopy.items.map(\.body).joined(separator: "\n")
        XCTAssertTrue(bodies.contains("点空白"))
        XCTAssertTrue(bodies.contains("⌘F"))
        XCTAssertTrue(bodies.contains("⌘K"))
        XCTAssertFalse(bodies.contains("不复刻浮栏"))
    }

    func testReopeningGuide_doesNotResetOnboarding() {
        XCTAssertFalse(UsageGuidePresentationPolicy.shouldResetOnboardingOnReopen)
        XCTAssertTrue(UsageGuidePresentationPolicy.shouldPresentGuideAfterFirstRun)
        XCTAssertTrue(UsageGuidePresentationPolicy.marksOnboardingComplete(reopenOnly: false))
        XCTAssertFalse(UsageGuidePresentationPolicy.marksOnboardingComplete(reopenOnly: true))
    }

    func testSettingsAndHelp_reopenTheSameGuideWithoutResettingOnboarding() throws {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let settings = try String(
            contentsOf: root.appendingPathComponent("Lumina/Features/Settings/SettingsView.swift"),
            encoding: .utf8
        )
        let app = try String(
            contentsOf: root.appendingPathComponent("Lumina/LuminaApp.swift"),
            encoding: .utf8
        )
        let content = try String(
            contentsOf: root.appendingPathComponent("Lumina/ContentView.swift"),
            encoding: .utf8
        )
        XCTAssertTrue(settings.contains("luminaOpenUsageGuide"))
        XCTAssertTrue(app.contains("Lumina 使用指南"))
        XCTAssertTrue(content.contains("UsageGuideSheet"))
        XCTAssertTrue(content.contains("shouldPresentGuideAfterFirstRun"))
        XCTAssertTrue(content.contains("marksOnboardingComplete(reopenOnly: false)"))
        XCTAssertFalse(content.contains("OnboardingView("))
        XCTAssertFalse(settings.contains("onboardingDone = false"))
        XCTAssertFalse(app.contains("onboardingDone = false"))
    }
}
