import XCTest
@testable import Lumina

final class MainWindowRevealPolicyTests: XCTestCase {
    func testAction_withVisibleWindow_ordersFront() {
        XCTAssertEqual(
            MainWindowRevealPolicy.action(for: [
                .init(isVisible: true, isMiniaturized: false),
            ]),
            .orderFrontExisting
        )
    }

    func testAction_withOnlyMiniaturizedWindow_ordersFront() {
        XCTAssertEqual(
            MainWindowRevealPolicy.action(for: [
                .init(isVisible: false, isMiniaturized: true),
            ]),
            .orderFrontExisting
        )
    }

    func testHelpTagAlone_isNotAMainWindow() {
        let tooltip = MainWindowRevealPolicy.WindowState(
            isVisible: true,
            isMiniaturized: false,
            isHelpTag: true,
            isPanel: true
        )
        XCTAssertFalse(MainWindowRevealPolicy.countsAsMainWindow(tooltip))
        XCTAssertEqual(
            MainWindowRevealPolicy.action(for: [tooltip]),
            .requestOpenMainWindow
        )
        XCTAssertEqual(
            MainWindowRevealPolicy.revealStep(for: tooltip),
            .dismissHelpTag
        )
    }

    func testHelpTagBesideMainWindow_isDismissedNotOrderedFront() {
        let main = MainWindowRevealPolicy.WindowState(isVisible: true, isMiniaturized: false)
        let tooltip = MainWindowRevealPolicy.WindowState(
            isVisible: true,
            isMiniaturized: false,
            isHelpTag: true,
            isPanel: true
        )
        XCTAssertEqual(
            MainWindowRevealPolicy.action(for: [main, tooltip]),
            .orderFrontExisting
        )
        XCTAssertEqual(MainWindowRevealPolicy.revealStep(for: main), .orderFront)
        XCTAssertEqual(MainWindowRevealPolicy.revealStep(for: tooltip), .dismissHelpTag)
    }

    func testHiddenHelpTag_isStillDismissed() {
        let hiddenTip = MainWindowRevealPolicy.WindowState(
            isVisible: false,
            isMiniaturized: false,
            isHelpTag: true
        )
        XCTAssertEqual(MainWindowRevealPolicy.revealStep(for: hiddenTip), .dismissHelpTag)
        XCTAssertNil(
            MainWindowRevealPolicy.revealStep(
                for: .init(isVisible: false, isMiniaturized: false)
            )
        )
    }

    func testIsHelpTagWindow_matchesTooltipClassNames() {
        XCTAssertTrue(MainWindowRevealPolicy.isHelpTagWindow(className: "_NSTooltipPanel"))
        XCTAssertTrue(MainWindowRevealPolicy.isHelpTagWindow(className: "NSToolTipPanel"))
        XCTAssertFalse(MainWindowRevealPolicy.isHelpTagWindow(className: "NSWindow"))
        XCTAssertFalse(MainWindowRevealPolicy.isHelpTagWindow(className: "NSPanel"))
    }

    func testAction_withNoUsableWindows_requestsOpen() {
        XCTAssertEqual(
            MainWindowRevealPolicy.action(for: []),
            .requestOpenMainWindow
        )
        XCTAssertEqual(
            MainWindowRevealPolicy.action(for: [
                .init(isVisible: false, isMiniaturized: false),
            ]),
            .requestOpenMainWindow
        )
    }

    func testHandoff_alwaysPostsReveal() {
        XCTAssertTrue(MainWindowRevealPolicy.shouldPostRevealWithForwardedPaths([]))
        XCTAssertTrue(
            MainWindowRevealPolicy.shouldPostRevealWithForwardedPaths(["/tmp/a.epub"])
        )
    }

    func testRevealURL_usesLuminaScheme() {
        XCTAssertTrue(MainWindowRevealPolicy.isRevealURL(MainWindowRevealPolicy.revealURL))
        XCTAssertFalse(
            MainWindowRevealPolicy.isRevealURL(URL(fileURLWithPath: "/tmp/a.epub"))
        )
    }

    func testDistributedUserInfo_includesRevealFlag() {
        let info = MainWindowRevealPolicy.distributedUserInfo(
            paths: ["/tmp/a.epub"],
            reveal: true
        )
        XCTAssertEqual(info["paths"] as? [String], ["/tmp/a.epub"])
        XCTAssertEqual(info["reveal"] as? Bool, true)
    }

    func testLuminaApp_revealsMainWindowOnExternalOpen() throws {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let app = try String(
            contentsOf: macosRoot.appendingPathComponent("Lumina/LuminaApp.swift"),
            encoding: .utf8
        )
        XCTAssertTrue(app.contains("WindowGroup"), "file-open needs WindowGroup primary scene")
        XCTAssertTrue(app.contains("revealMainWindow"), "open/reopen/handoff must reveal UI")
        XCTAssertTrue(app.contains("handlesExternalEvents"))
        XCTAssertTrue(
            app.contains("MainWindowRevealPolicy.revealURL")
                || app.contains("lumina://reveal"),
            "closed-window fallback must open reveal URL"
        )
        let content = try String(
            contentsOf: macosRoot.appendingPathComponent("Lumina/ContentView.swift"),
            encoding: .utf8
        )
        XCTAssertTrue(
            content.contains("AppDelegate.revealMainWindow()"),
            "external open handler must bring the main window forward"
        )

        let reveal = app
            .components(separatedBy: "static func revealMainWindow()").last?
            .components(separatedBy: "private static func windowState").first ?? ""
        XCTAssertTrue(reveal.contains("dismissHelpTags"))
        XCTAssertTrue(app.contains("abortDisplayedToolTip"))
        XCTAssertTrue(app.contains("window.orderOut(nil)"))
        XCTAssertTrue(app.contains("isHelpTagWindow"))
        XCTAssertFalse(
            reveal.contains("for window in NSApp.windows"),
            "ordering every window makes the help tag key and leaves 「点击预览新分界」"
        )
        let dismiss = reveal.range(of: "dismissHelpTags")
        let order = reveal.range(of: "orderFrontContentWindows")
        XCTAssertNotNil(dismiss)
        XCTAssertNotNil(order)
        if let dismiss, let order {
            XCTAssertLessThan(dismiss.lowerBound, order.lowerBound)
        }
    }
}
