import XCTest
@testable import Lumina

final class ImportConflictPolicyTests: XCTestCase {
    func testSkipRemaining_skipsCurrentAndKeepsImportingNewBooks() {
        let decision = ImportConflictPolicy.decision(for: .skipRemainingDuplicates)
        XCTAssertFalse(decision.overwriteCurrent)
        XCTAssertTrue(decision.skipRemainingDuplicates)
        XCTAssertTrue(decision.continueQueue)
    }

    func testCancelRemaining_stopsQueueIncludingNewBooks() {
        let decision = ImportConflictPolicy.decision(for: .cancelRemaining)
        XCTAssertFalse(decision.overwriteCurrent)
        XCTAssertFalse(decision.skipRemainingDuplicates)
        XCTAssertFalse(decision.continueQueue)
    }

    func testSkipOnce_stillPromptsLaterConflicts() {
        let decision = ImportConflictPolicy.decision(for: .skip)
        XCTAssertFalse(decision.skipRemainingDuplicates)
        XCTAssertTrue(decision.continueQueue)
        XCTAssertTrue(ImportConflictPolicy.shouldPrompt(skipRemainingDuplicates: false))
        XCTAssertFalse(ImportConflictPolicy.shouldPrompt(skipRemainingDuplicates: true))
    }

    func testOverwrite_doesNotArmSkipRemaining() {
        let decision = ImportConflictPolicy.decision(for: .overwrite)
        XCTAssertTrue(decision.overwriteCurrent)
        XCTAssertFalse(decision.skipRemainingDuplicates)
        XCTAssertTrue(decision.continueQueue)
    }

    func testShowsSkipRemaining_onlyWhenQueueHasMoreFiles() {
        XCTAssertFalse(ImportConflictPolicy.showsSkipRemaining(pendingCount: 0))
        XCTAssertTrue(ImportConflictPolicy.showsSkipRemaining(pendingCount: 1))
    }

    func testDialogMessage_explainsSkipRemainingWhenQueueRemains() {
        let single = ImportConflictPolicy.dialogMessage(title: "旧书", remainingCount: 0)
        XCTAssertTrue(single.contains("《旧书》已在书库中"))
        XCTAssertFalse(single.contains("跳过剩下所有"))

        let batch = ImportConflictPolicy.dialogMessage(title: "旧书", remainingCount: 3)
        XCTAssertTrue(batch.contains("跳过剩下所有"))
        XCTAssertTrue(batch.contains("仍导入新书"))
    }
}
