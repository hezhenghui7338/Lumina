import XCTest
@testable import Lumina

final class ReaderChromeClickPolicyTests: XCTestCase {
    func testHiddenChromeIsRevealed() {
        XCTAssertEqual(
            ReaderChromeClickPolicy.outcome(
                overlayOpen: false,
                segmentPeekVisible: false,
                chromeHidden: true
            ),
            .reveal
        )
    }

    func testVisibleChromeCollapses() {
        XCTAssertEqual(
            ReaderChromeClickPolicy.outcome(
                overlayOpen: false,
                segmentPeekVisible: false,
                chromeHidden: false
            ),
            .collapse
        )
    }

    func testSegmentPeekRetractsBeforeChromeChanges() {
        for chromeHidden in [true, false] {
            XCTAssertEqual(
                ReaderChromeClickPolicy.outcome(
                    overlayOpen: false,
                    segmentPeekVisible: true,
                    chromeHidden: chromeHidden
                ),
                .closeSegmentPeek,
                "peeked segment list must retract first (chromeHidden=\(chromeHidden))"
            )
        }
    }

    func testOpenOverlayOwnsTheClick() {
        for segmentPeekVisible in [true, false] {
            for chromeHidden in [true, false] {
                XCTAssertEqual(
                    ReaderChromeClickPolicy.outcome(
                        overlayOpen: true,
                        segmentPeekVisible: segmentPeekVisible,
                        chromeHidden: chromeHidden
                    ),
                    .ignore
                )
            }
        }
    }
}

/// Locks the architecture that fixed reader control clicks toggling the chrome.
///
/// Measured on macOS 15: a SwiftUI Button, a text label and blank space all
/// hit-test to the same `PlatformGroupContainer`, and `.buttonStyle(.bordered)`
/// creates no `NSButton` at all — so an AppKit hit-test walk can never tell a
/// control click from a reading click, and every reader button ends up toggling
/// the chrome. Ownership must stay with SwiftUI hit-testing: the frontmost
/// handler (the Button) takes the click, and only clicks that reach the reading
/// surface call `toggleChromeOnBlankClick()`.
final class ReaderChromeClickArchitectureTests: XCTestCase {
    private func source(_ relativePath: String) throws -> String {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()  // Unit
            .deletingLastPathComponent()  // LuminaTests
            .deletingLastPathComponent()  // macos
        return try String(
            contentsOf: macosRoot.appendingPathComponent(relativePath),
            encoding: .utf8
        )
    }

    private func readerSource() throws -> String {
        try source("Lumina/Features/Reader/ReaderView.swift")
    }

    func testReaderNeverGuessesControlsFromAppKitOrAccessibility() throws {
        let source = try readerSource()
        for banned in [
            "ChromeClickTracker",
            "ChromeClickNSView",
            "ChromeClickHitPolicy",
            "AXUIElementCopyElementAtPosition",
            "isPointInReaderDocument",
            "addLocalMonitorForEvents(matching: .leftMouseDown",
            "addLocalMonitorForEvents(matching: .leftMouseUp",
        ] {
            XCTAssertFalse(
                source.contains(banned),
                "\(banned) resurrects control-hit guessing, which makes every reader button toggle the chrome"
            )
        }
    }

    func testReaderFeedOwnsTheChromeToggleGesture() throws {
        let source = try readerSource()
        XCTAssertTrue(
            source.contains(".onTapGesture { toggleChromeOnBlankClick() }"),
            "the reader feed must own the chrome toggle so controls can outrank it"
        )
        XCTAssertEqual(
            source.components(separatedBy: "toggleChromeOnBlankClick()").count - 1,
            2,
            "exactly one caller (the feed tap) plus the definition may exist"
        )
    }

    func testDisableableControlStripsKeepTheirOwnClicks() throws {
        let block = try source("Lumina/Features/Reader/SegmentReadingBlock.swift")
        XCTAssertEqual(
            block.components(separatedBy: ".absorbsReaderChromeClicks()").count - 1,
            2,
            "the panel toggle strip and the segment turn strip both hold disabled "
                + "buttons, which are not hit-testable and would leak clicks to the chrome toggle"
        )
    }
}

/// A 1Hz `@Published` clock on the reader view model rebuilds the window
/// toolbar and every `.help()` control. AppKit then re-shows Help Tags and
/// auto-dismisses them on the next tick.
final class ReaderHelpTooltipPolicyTests: XCTestCase {
    func testShouldApply_skipsUnchangedToolbarVisibility() {
        XCTAssertTrue(WindowToolbarVisibilityPolicy.shouldApply(applied: nil, desired: true))
        XCTAssertTrue(WindowToolbarVisibilityPolicy.shouldApply(applied: false, desired: true))
        XCTAssertTrue(WindowToolbarVisibilityPolicy.shouldApply(applied: true, desired: false))
        XCTAssertFalse(WindowToolbarVisibilityPolicy.shouldApply(applied: true, desired: true))
        XCTAssertFalse(WindowToolbarVisibilityPolicy.shouldApply(applied: false, desired: false))
    }

    func testReaderDoesNotPublishOneHertzHelpTagClock() throws {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let reader = try String(
            contentsOf: macosRoot.appendingPathComponent("Lumina/Features/Reader/ReaderView.swift"),
            encoding: .utf8
        )
        for banned in ["sidebarClock", "sidebarClockTask", "setSidebarVisible", "statusClock"] {
            XCTAssertFalse(
                reader.contains(banned),
                "\(banned) republishes the whole reader every second and retriggers button help tags"
            )
        }
        XCTAssertTrue(
            reader.contains("TimelineView(.periodic(from: .now, by: 1))"),
            "sidebar live captions must tick locally via TimelineView, not a view-model clock"
        )
    }

    func testWindowToolbarVisibility_gatesReapply() throws {
        let macosRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let source = try String(
            contentsOf: macosRoot.appendingPathComponent("Lumina/Design/WindowToolbarVisibility.swift"),
            encoding: .utf8
        )
        XCTAssertTrue(source.contains("WindowToolbarVisibilityPolicy.shouldApply"))
        XCTAssertTrue(source.contains("setDesiredVisible"))
        XCTAssertFalse(
            source.contains("didSet { applyVisibility() }"),
            "didSet on every SwiftUI updateNSView retriggers help tags"
        )
    }
}
