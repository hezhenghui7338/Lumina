import XCTest
@testable import Lumina

final class OnboardingTourPolicyTests: XCTestCase {
    func testEmptyLibrary_hasFourStepsEndingInOverview() {
        let steps = OnboardingTourPolicy.steps(hasOpenableBook: false)
        XCTAssertEqual(
            steps,
            [.importBook, .openBook, .configureAPI, .readerOverview]
        )
        XCTAssertEqual(
            OnboardingTourPolicy.primaryButtonTitle(
                for: .readerOverview,
                hasOpenableBook: false
            ),
            "知道了"
        )
        XCTAssertEqual(
            OnboardingTourPolicy.next(after: .configureAPI, hasOpenableBook: false),
            .readerOverview
        )
        XCTAssertNil(
            OnboardingTourPolicy.next(after: .readerOverview, hasOpenableBook: false)
        )
    }

    func testLibraryWithBooks_opensReaderAfterAPI() {
        XCTAssertEqual(OnboardingTourPolicy.count(hasOpenableBook: true), 7)
        XCTAssertEqual(
            OnboardingTourPolicy.next(after: .configureAPI, hasOpenableBook: true),
            .summarize
        )
        XCTAssertEqual(OnboardingTourPolicy.surface(for: .summarize), .reader)
        XCTAssertEqual(
            OnboardingTourPolicy.primaryButtonTitle(for: .notes, hasOpenableBook: true),
            "知道了"
        )
        XCTAssertNil(OnboardingTourPolicy.next(after: .notes, hasOpenableBook: true))
    }

    func testResolve_upgradesOverviewWhenBooksAppear() {
        XCTAssertEqual(
            OnboardingTourPolicy.resolve(.readerOverview, hasOpenableBook: true),
            .summarize
        )
        XCTAssertEqual(
            OnboardingTourPolicy.resolve(.summarize, hasOpenableBook: false),
            .readerOverview
        )
    }

    func testImportAnchor_dependsOnBooks() {
        XCTAssertEqual(
            OnboardingTourPolicy.anchor(for: .importBook, hasOpenableBook: false),
            .importButton
        )
        XCTAssertEqual(
            OnboardingTourPolicy.anchor(for: .importBook, hasOpenableBook: true),
            .bookshelf
        )
    }

    func testContentView_startsTourWithoutWaitingForSidecar() throws {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let content = try String(
            contentsOf: macosRoot.appendingPathComponent("Lumina/ContentView.swift"),
            encoding: .utf8
        )
        XCTAssertTrue(content.contains("tour.start()"))
        XCTAssertFalse(content.contains("showOnboarding"))
        XCTAssertFalse(content.contains("OnboardingView("))
        // PRD §3.4: spotlight 结束后弹出使用指南；设置/Help 可再打开。不是重跑 spotlight。
        XCTAssertTrue(content.contains("UsageGuideSheet"))
        XCTAssertTrue(content.contains("showUsageGuide"))
        let bootstrap = content
            .components(separatedBy: "private func finishBootstrap()")
            .last?
            .components(separatedBy: "private func importBook()")
            .first ?? ""
        XCTAssertFalse(
            bootstrap.contains("tour.start()"),
            "first-run tour must not wait for sidecar"
        )
        XCTAssertTrue(content.contains("tour.skip()"))
        XCTAssertTrue(content.contains("onboardingDone = true"))

        let settings = try String(
            contentsOf: macosRoot.appendingPathComponent(
                "Lumina/Features/Settings/SettingsView.swift"
            ),
            encoding: .utf8
        )
        XCTAssertTrue(settings.contains("使用指南"))
        XCTAssertTrue(settings.contains("luminaOpenUsageGuide"))
        XCTAssertFalse(settings.contains("重新显示引导"))

        let app = try String(
            contentsOf: macosRoot.appendingPathComponent("Lumina/LuminaApp.swift"),
            encoding: .utf8
        )
        XCTAssertTrue(app.contains("Lumina 使用指南"))
        XCTAssertTrue(app.contains("luminaOpenUsageGuide"))

        let overlay = try String(
            contentsOf: macosRoot.appendingPathComponent(
                "Lumina/Features/Onboarding/OnboardingTourOverlay.swift"
            ),
            encoding: .utf8
        )
        XCTAssertTrue(
            overlay.contains(".allowsHitTesting(false)"),
            "dim overlay must not freeze tabs or other controls"
        )
        XCTAssertFalse(overlay.contains("contentShape(SpotlightHoleShape"))
        XCTAssertTrue(
            overlay.contains("CGSize(width:"),
            "CGSize uses width/height labels; x/y will not compile"
        )
        XCTAssertFalse(overlay.contains("CGSize(x:"))

        let onboardingDir = macosRoot.appendingPathComponent("Lumina/Features/Onboarding")
        XCTAssertTrue(
            FileManager.default.fileExists(
                atPath: onboardingDir.appendingPathComponent("UsageGuideCopy.swift").path
            )
        )
        XCTAssertTrue(
            FileManager.default.fileExists(
                atPath: onboardingDir.appendingPathComponent("UsageGuideView.swift").path
            )
        )
        XCTAssertFalse(
            FileManager.default.fileExists(
                atPath: onboardingDir.appendingPathComponent("OnboardingView.swift").path
            ),
            "three-step OnboardingView must stay deleted; spotlight + usage sheet replaced it"
        )
    }
}

@MainActor
final class OnboardingTourControllerTests: XCTestCase {
    func testAdvanceAndSkip_writeCompleted() {
        let tour = OnboardingTourController()
        tour.start()
        XCTAssertTrue(tour.isActive)
        XCTAssertEqual(tour.step, .importBook)
        tour.advance()
        XCTAssertEqual(tour.step, .openBook)
        tour.skip()
        XCTAssertFalse(tour.isActive)
        XCTAssertTrue(tour.completed)
        XCTAssertNil(tour.step)
    }

    func testSyncLibrary_opensReaderPath() {
        let tour = OnboardingTourController()
        tour.start()
        tour.advance()
        tour.advance()
        XCTAssertEqual(tour.step, .configureAPI)
        tour.syncLibrary(hasOpenableBook: true, firstBookId: "b1")
        tour.advance()
        XCTAssertEqual(tour.step, .summarize)
        XCTAssertEqual(tour.firstOpenableBookId, "b1")
    }
}
