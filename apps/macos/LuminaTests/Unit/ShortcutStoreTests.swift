import XCTest
@testable import Lumina

@MainActor
final class ShortcutStoreTests: XCTestCase {
    private var store: ShortcutStore!
    private var defaults: UserDefaults!
    private var suiteName: String!

    override func setUp() {
        super.setUp()
        suiteName = "lumina.tests.shortcuts.\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suiteName)!
        store = ShortcutStore(defaults: defaults)
    }

    override func tearDown() {
        defaults.removePersistentDomain(forName: suiteName)
        store = nil
        defaults = nil
        suiteName = nil
        super.tearDown()
    }

    func testDefaults_coverEveryAction() {
        for action in ShortcutAction.allCases {
            XCTAssertNotNil(ShortcutCatalog.defaults[action], action.rawValue)
            XCTAssertFalse(store.display(for: action).isEmpty, action.rawValue)
        }
    }

    func testSetChord_rejectsReserved() {
        let chord = ShortcutChord(keyCode: 12, character: "q", modifiers: .command)
        XCTAssertEqual(store.setChord(chord, for: .startSummarize), .reserved)
        XCTAssertFalse(store.isOverridden(.startSummarize))
    }

    func testSetChord_detectsConflict() {
        let chord = ShortcutCatalog.defaultChord(for: .originalSearch)
        let result = store.setChord(chord, for: .startSummarize)
        XCTAssertEqual(result, .conflict(.originalSearch))
    }

    func testSetChord_andReset() {
        let chord = ShortcutChord(keyCode: 15, character: "r", modifiers: [.command, .control])
        XCTAssertEqual(store.setChord(chord, for: .startSummarize), .ok)
        XCTAssertTrue(store.isOverridden(.startSummarize))
        XCTAssertEqual(store.display(for: .startSummarize), "⌃⌘R")
        store.reset(.startSummarize)
        XCTAssertFalse(store.isOverridden(.startSummarize))
        XCTAssertEqual(store.display(for: .startSummarize), "R")
    }

    func testDefaults_preferAtMostTwoKeys() {
        for action in ShortcutCatalog.customizableActions {
            let mods = ShortcutCatalog.defaultChord(for: action).modifiers
            let modifierCount = [ShortcutModifiers.command, .shift, .option, .control]
                .filter { mods.contains($0) }
                .count
            XCTAssertLessThanOrEqual(
                modifierCount,
                1,
                "\(action.rawValue) default should not use ⌘⇧ / ⌘⌥ style chords"
            )
        }
    }

    func testResetAll() {
        let chord = ShortcutChord(keyCode: 15, character: "r", modifiers: [.command, .control])
        _ = store.setChord(chord, for: .startSummarize)
        _ = store.setChord(
            ShortcutChord(keyCode: 37, character: "l", modifiers: [.command, .control]),
            for: .toggleListen
        )
        store.resetAll()
        XCTAssertFalse(store.isOverridden(.startSummarize))
        XCTAssertFalse(store.isOverridden(.toggleListen))
    }

    func testFixedActions_notCustomizable() {
        let chord = ShortcutChord(keyCode: 15, character: "r", modifiers: [.command, .control])
        XCTAssertEqual(store.setChord(chord, for: .dismissOverlay), .notCustomizable)
    }

    func testDangerousMenuActions_areMenuOnlyInCatalogCopy() {
        XCTAssertTrue(ShortcutAction.openSummarizeMenu.detail?.contains("只打开") == true)
        XCTAssertTrue(ShortcutAction.openSegmentMenu.detail?.contains("只打开") == true)
    }
}
